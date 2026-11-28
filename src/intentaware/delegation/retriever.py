"""有界公开来源检索器：只依赖标准库，严格限制最多返回两份公开网页材料。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import CancelledError
from html import unescape
from html.parser import HTMLParser
import http.client
import ipaddress
import json
import re
import socket
from threading import Event
from time import monotonic
from typing import Protocol
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest

from intentaware.localization import tr
from .config import DelegationConfig
from .errors import DelegationNetworkError, DelegationTimeoutError
from .models import RetrievedDocument, SearchHit

HttpGet = Callable[[str, Mapping[str, str], float], tuple[bytes, str]]
HttpPostJson = Callable[[str, dict, Mapping[str, str], float], bytes]

_USER_AGENT = "IntentAware-Delegation/0.1 (COMP7607-Group14; +https://github.com/Ir1svanquish/IntentAware-Agent)"
_MAX_FETCH_BYTES = 512 * 1024
_IGNORED_TAGS = frozenset({"script", "style", "noscript", "svg", "iframe", "template"})
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_TAG_RE = re.compile(r"<[^>]+>")


class Retriever(Protocol):
    """公开来源检索协议：返回最多 max_sources (<=2) 份材料，并响应 cancel。"""

    def retrieve(
        self, query: str, *, max_sources: int = 2, cancel: Event | None = None
    ) -> list[RetrievedDocument]:
        ...


def _check_cancel(cancel: Event | None) -> None:
    if cancel is not None and cancel.is_set():
        raise CancelledError(tr("委托任务已取消。"))


def is_public_http_url(url: str) -> bool:
    """只允许公开可访问的 http(s) 地址，拦截内网、回环和本地域名。"""
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlparse.urlsplit(url.strip())
    except ValueError:
        return False
    if parsed.scheme.lower() not in ("http", "https"):
        return False
    if parsed.username is not None or parsed.password is not None:
        return False
    host = parsed.hostname
    if not host:
        return False
    lowered = host.lower().rstrip(".")
    if lowered == "localhost" or lowered.endswith((".local", ".internal", ".localhost", ".arpa")):
        return False
    try:
        ip = ipaddress.ip_address(lowered)
    except ValueError:
        return "." in lowered
    return _is_public_ip(ip)


def _is_public_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_global
        and not ip.is_private
        and not ip.is_loopback
        and not ip.is_link_local
        and not ip.is_multicast
        and not ip.is_reserved
        and not ip.is_unspecified
    )


def _normalize_url(url: str) -> str:
    parsed = urlparse.urlsplit(url.strip())
    return urlparse.urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path, parsed.query, ""))


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._in_title = False
        self.title_parts: list[str] = []
        self.body_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        lower = tag.lower()
        if lower in _IGNORED_TAGS:
            self._skip_depth += 1
            return
        if lower == "title" and self._skip_depth == 0:
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if lower in _IGNORED_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
            return
        if lower == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0 or not data.strip():
            return
        if self._in_title:
            self.title_parts.append(data)
        else:
            self.body_parts.append(data)


def extract_html_text(raw_html: str, *, max_chars: int = 2500) -> tuple[str, str]:
    """提取网页标题和正文中前 max_chars 字符，过滤脚本与样式。"""
    parser = _TextExtractor()
    parser.feed(raw_html)
    parser.close()
    title = re.sub(r"\s+", " ", " ".join(parser.title_parts)).strip()
    body = re.sub(r"\s+", " ", " ".join(parser.body_parts)).strip()
    if len(body) > max_chars:
        body = body[: max_chars - 1].rstrip() + "…"
    return title, body


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._title_depth = 0
        self._snippet_depth = 0
        self._snippet_tag = ""
        self._current_href = ""
        self._title_buf: list[str] = []
        self._snippet_buf: list[str] = []
        self.hits: list[SearchHit] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        lower = tag.lower()
        attr_map = dict(attrs)
        classes = set((attr_map.get("class") or "").split())
        if self._title_depth > 0 and lower == "a":
            self._title_depth += 1
        elif lower == "a" and ("result__a" in classes or "result-link" in classes):
            self._title_depth = 1
            self._current_href = attr_map.get("href") or ""
            self._title_buf = []
        elif self._snippet_depth > 0 and lower == self._snippet_tag:
            self._snippet_depth += 1
        elif self._snippet_depth == 0 and lower in ("a", "div", "span") and (
            "result__snippet" in classes or "result-snippet" in classes
        ):
            self._snippet_tag = lower
            self._snippet_depth = 1
            self._snippet_buf = []

    def handle_endtag(self, tag: str) -> None:
        lower = tag.lower()
        if self._title_depth > 0 and lower == "a":
            self._title_depth -= 1
            if self._title_depth == 0:
                url = _unwrap_ddg_url(self._current_href)
                title = re.sub(r"\s+", " ", "".join(self._title_buf)).strip()
                if title and url:
                    self.hits.append(SearchHit(title=title, url=url))
        elif self._snippet_depth > 0 and lower == self._snippet_tag:
            self._snippet_depth -= 1
            if self._snippet_depth == 0:
                self._snippet_tag = ""
                snippet = re.sub(r"\s+", " ", "".join(self._snippet_buf)).strip()
                if snippet and self.hits and not self.hits[-1].snippet:
                    last = self.hits[-1]
                    self.hits[-1] = SearchHit(title=last.title, url=last.url, snippet=snippet)

    def handle_data(self, data: str) -> None:
        if self._title_depth > 0:
            self._title_buf.append(data)
        elif self._snippet_depth > 0:
            self._snippet_buf.append(data)


def _unwrap_ddg_url(href: str) -> str:
    raw = href.strip()
    if raw.startswith("//"):
        raw = "https:" + raw
    elif raw.startswith("/"):
        raw = "https://duckduckgo.com" + raw
    parsed = urlparse.urlsplit(raw)
    if "duckduckgo.com" in (parsed.hostname or "") and parsed.path.startswith("/l/"):
        uddg = urlparse.parse_qs(parsed.query).get("uddg")
        if uddg:
            return urlparse.unquote(uddg[0])
    return raw


class _PublicRedirectHandler(urlrequest.HTTPRedirectHandler):
    """在跟随 HTTP 重定向前校验目标 URL，防止跳转到内网或本地地址。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlparse.urljoin(req.full_url, newurl)
        if not is_public_http_url(target):
            raise urlerror.URLError(tr("已拦截指向非公开地址的重定向。"))
        return super().redirect_request(req, fp, code, msg, headers, target)


def _connect_public(address, timeout: float, source_address=None):
    host, port = address
    deadline = monotonic() + timeout
    endpoints = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
    if not endpoints or any(not _is_public_ip(ipaddress.ip_address(item[4][0])) for item in endpoints):
        raise OSError(tr("公开检索只允许连接公网地址。"))

    last_error = None
    for family, kind, proto, _, sockaddr in endpoints:
        remaining = deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError(tr("公开检索连接超时。"))
        conn = socket.socket(family, kind, proto)
        try:
            conn.settimeout(remaining)
            if source_address is not None:
                conn.bind(source_address)
            conn.connect(sockaddr)
            conn.settimeout(timeout)
            return conn
        except OSError as error:
            conn.close()
            last_error = error
    raise last_error


class _PublicHTTPConnection(http.client.HTTPConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._create_connection = _connect_public


class _PublicHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Keep the original hostname for TLS SNI and certificate verification.
        self._create_connection = _connect_public


class _PublicHTTPHandler(urlrequest.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_PublicHTTPConnection, req)


class _PublicHTTPSHandler(urlrequest.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_PublicHTTPSConnection, req)


def _default_http_get(url: str, headers: Mapping[str, str], timeout: float) -> tuple[bytes, str]:
    if not is_public_http_url(url):
        raise urlerror.URLError(tr("公开检索只允许请求公开 HTTP(S) 地址。"))
    req = urlrequest.Request(url, headers=dict(headers), method="GET")
    opener = urlrequest.build_opener(
        urlrequest.ProxyHandler({}), _PublicHTTPHandler(), _PublicHTTPSHandler(), _PublicRedirectHandler()
    )
    with opener.open(req, timeout=timeout) as resp:
        data = resp.read(_MAX_FETCH_BYTES)
        content_type = resp.headers.get("Content-Type", "")
        return data, content_type


def _default_http_post_json(
    url: str, payload: dict, headers: Mapping[str, str], timeout: float
) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urlrequest.Request(url, data=body, headers=dict(headers), method="POST")
    with urlrequest.urlopen(req, timeout=timeout) as resp:
        return resp.read(_MAX_FETCH_BYTES)


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, (TimeoutError, socket.timeout))


def _translate_http_error(exc: BaseException, timeout: float, action: str) -> DelegationNetworkError | DelegationTimeoutError:
    if _is_timeout(exc):
        return DelegationTimeoutError(tr("{0}超过 {1:g} 秒未响应。", action, timeout))
    if isinstance(exc, urlerror.HTTPError):
        return DelegationNetworkError(tr("{0}返回 HTTP {1}。", action, exc.code))
    return DelegationNetworkError(tr("{0}失败，请检查网络连接。", action))


class DuckDuckGoSearchProvider:
    """免 Key 公开搜索：解析 DuckDuckGo HTML 公开结果。"""

    def __init__(self, http_get: HttpGet = _default_http_get):
        self.http_get = http_get

    def search(self, query: str, *, max_results: int, timeout: float) -> list[SearchHit]:
        encoded = urlparse.quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded}"
        headers = {"User-Agent": _USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
        try:
            raw, _ = self.http_get(url, headers, timeout)
        except (urlerror.HTTPError, urlerror.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise _translate_http_error(exc, timeout, tr("公开搜索请求")) from None

        parser = _DuckDuckGoParser()
        parser.feed(raw.decode("utf-8", errors="replace"))
        parser.close()
        return parser.hits[: max(max_results * 2, 4)]


class WikipediaSearchProvider:
    """免 Key 兜底检索：使用维基百科公开 MediaWiki OpenSearch API。"""

    def __init__(self, http_get: HttpGet = _default_http_get):
        self.http_get = http_get

    def search(self, query: str, *, max_results: int, timeout: float) -> list[SearchHit]:
        lang = "zh" if _CJK_RE.search(query) else "en"
        params = urlparse.urlencode(
            {
                "action": "query",
                "list": "search",
                "format": "json",
                "utf8": "1",
                "srlimit": str(max(max_results * 2, 4)),
                "srsearch": query,
            }
        )
        url = f"https://{lang}.wikipedia.org/w/api.php?{params}"
        headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
        try:
            raw, _ = self.http_get(url, headers, timeout)
        except (urlerror.HTTPError, urlerror.URLError, TimeoutError, socket.timeout, OSError) as exc:
            raise _translate_http_error(exc, timeout, tr("维基百科检索")) from None

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise DelegationNetworkError(tr("维基百科检索返回了无法解析的数据。")) from None

        items = payload.get("query", {}).get("search", [])
        if not isinstance(items, list):
            return []
        hits: list[SearchHit] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            if not title:
                continue
            page_url = f"https://{lang}.wikipedia.org/wiki/{urlparse.quote(title.replace(' ', '_'))}"
            raw_snippet = str(item.get("snippet") or "")
            snippet = re.sub(r"\s+", " ", unescape(_TAG_RE.sub(" ", raw_snippet))).strip()
            hits.append(SearchHit(title=title, url=page_url, snippet=snippet))
        return hits


class TavilySearchProvider:
    """可选 Tavily 搜索 API，提升 40 条留出样本批量实验时的稳定性。"""

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = "",
        http_post_json: HttpPostJson = _default_http_post_json,
    ):
        self.api_key = api_key
        self.endpoint = (base_url or "https://api.tavily.com/search").rstrip("/")
        self.http_post_json = http_post_json

    def search(self, query: str, *, max_results: int, timeout: float) -> list[SearchHit]:
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max(1, min(max_results, 4)),
            "search_depth": "basic",
        }
        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "User-Agent": _USER_AGENT,
        }
        try:
            raw = self.http_post_json(self.endpoint, payload, headers, timeout)
        except (urlerror.HTTPError, urlerror.URLError, TimeoutError, socket.timeout, OSError) as exc:
            if isinstance(exc, urlerror.HTTPError) and exc.code in (401, 403):
                raise DelegationNetworkError(tr("Tavily 鉴权失败（HTTP {0}），请检查搜索密钥。", exc.code)) from None
            raise _translate_http_error(exc, timeout, tr("Tavily 搜索请求")) from None

        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise DelegationNetworkError(tr("Tavily 返回了非 JSON 数据。")) from None

        results = data.get("results", [])
        if not isinstance(results, list):
            return []
        hits: list[SearchHit] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "").strip()
            url = str(item.get("url") or "").strip()
            snippet = str(item.get("content") or "").strip()
            if title and url:
                hits.append(SearchHit(title=title, url=url, snippet=snippet))
        return hits


class PublicWebRetriever:
    """有界公开来源检索：最多抓取并保留 2 份公开网页材料，全程支持 cancel 与有限超时。"""

    def __init__(
        self,
        config: DelegationConfig | None = None,
        *,
        http_get: HttpGet = _default_http_get,
        http_post_json: HttpPostJson = _default_http_post_json,
        primary_provider=None,
        fallback_provider=None,
    ):
        self.config = config or DelegationConfig()
        self.http_get = http_get
        self.http_post_json = http_post_json
        if primary_provider is not None:
            self.primary_provider = primary_provider
            self.fallback_provider = fallback_provider
        elif self.config.search_provider == "tavily":
            self.primary_provider = TavilySearchProvider(
                self.config.search_api_key,
                base_url=self.config.search_base_url,
                http_post_json=self.http_post_json,
            )
            self.fallback_provider = None
        else:
            self.primary_provider = DuckDuckGoSearchProvider(http_get=self.http_get)
            self.fallback_provider = (
                fallback_provider
                if fallback_provider is not None
                else WikipediaSearchProvider(http_get=self.http_get)
            )

    def retrieve(
        self, query: str, *, max_sources: int = 2, cancel: Event | None = None
    ) -> list[RetrievedDocument]:
        cleaned_query = query.strip()
        if not cleaned_query:
            raise ValueError(tr("检索问题不能为空。"))
        _check_cancel(cancel)

        limit = max(1, min(max_sources, self.config.max_sources, 2))
        hits = self._search_hits(cleaned_query, limit=limit, cancel=cancel)
        _check_cancel(cancel)

        seen_urls: set[str] = set()
        candidates: list[SearchHit] = []
        for hit in hits:
            if not is_public_http_url(hit.url):
                continue
            normalized = _normalize_url(hit.url)
            if normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            candidates.append(hit)
            if len(candidates) == limit:
                break

        documents: list[RetrievedDocument] = []
        for hit in candidates:
            _check_cancel(cancel)
            doc = self._fetch_document(hit, source_id=f"S{len(documents) + 1}")
            _check_cancel(cancel)
            if doc is not None:
                documents.append(doc)
        return documents

    def _search_hits(self, query: str, *, limit: int, cancel: Event | None) -> list[SearchHit]:
        primary_error: Exception | None = None
        hits: list[SearchHit] = []
        try:
            hits = self.primary_provider.search(
                query, max_results=limit, timeout=self.config.search_timeout
            )
        except CancelledError:
            raise
        except (DelegationTimeoutError, DelegationNetworkError) as exc:
            primary_error = exc

        public_hits = [hit for hit in hits if is_public_http_url(hit.url)]
        if public_hits:
            return public_hits

        if self.fallback_provider is None:
            if primary_error is not None:
                raise primary_error
            return []

        _check_cancel(cancel)
        try:
            fallback_hits = self.fallback_provider.search(
                query, max_results=limit, timeout=self.config.search_timeout
            )
        except CancelledError:
            raise
        except (DelegationTimeoutError, DelegationNetworkError) as fallback_error:
            if isinstance(primary_error, DelegationTimeoutError) or isinstance(
                fallback_error, DelegationTimeoutError
            ):
                raise (
                    primary_error
                    if isinstance(primary_error, DelegationTimeoutError)
                    else fallback_error
                ) from None
            raise (primary_error or fallback_error) from None

        return [hit for hit in fallback_hits if is_public_http_url(hit.url)]

    def _fetch_document(self, hit: SearchHit, *, source_id: str) -> RetrievedDocument | None:
        headers = {"User-Agent": _USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9"}
        title = hit.title.strip()
        excerpt = ""
        try:
            raw, content_type = self.http_get(hit.url, headers, self.config.fetch_timeout)
            text = raw.decode("utf-8", errors="replace")
            if "html" in content_type.lower() or "<html" in text[:400].lower():
                parsed_title, parsed_body = extract_html_text(
                    text, max_chars=self.config.max_excerpt_chars
                )
                title = title or parsed_title or hit.url
                excerpt = parsed_body
            elif content_type.lower().startswith("text/"):
                cleaned = re.sub(r"\s+", " ", text).strip()
                excerpt = cleaned[: self.config.max_excerpt_chars]
        except (urlerror.HTTPError, urlerror.URLError, TimeoutError, socket.timeout, OSError):
            excerpt = ""

        if not excerpt or not title:
            return None
        return RetrievedDocument(
            source_id=source_id,
            title=title,
            url=hit.url.strip(),
            snippet=hit.snippet.strip(),
            excerpt=excerpt,
        )


class MockRetriever:
    """离线测试用检索器，支持预设文档、查询映射、异常注入和可中断延迟。"""

    def __init__(
        self,
        responses: Iterable[RetrievedDocument] | Mapping[str, Iterable[RetrievedDocument]] | Callable[[str, int], list[RetrievedDocument]] = (),
        *,
        delay_seconds: float = 0.0,
    ):
        self.responses = responses
        self.delay_seconds = delay_seconds
        self.calls: list[dict[str, object]] = []

    def retrieve(
        self, query: str, *, max_sources: int = 2, cancel: Event | None = None
    ) -> list[RetrievedDocument]:
        _check_cancel(cancel)
        self.calls.append({"query": query, "max_sources": max_sources})
        if self.delay_seconds > 0 and cancel is not None:
            if cancel.wait(self.delay_seconds):
                raise CancelledError(tr("委托任务已取消。"))
        _check_cancel(cancel)

        limit = max(1, min(max_sources, 2))
        if callable(self.responses):
            docs = list(self.responses(query, limit))
        elif isinstance(self.responses, Mapping):
            docs = list(self.responses.get(query, ()))
        else:
            docs = list(self.responses)

        normalized: list[RetrievedDocument] = []
        for idx, doc in enumerate(docs[:limit], start=1):
            if isinstance(doc, BaseException):
                raise doc
            normalized.append(
                RetrievedDocument(
                    source_id=doc.source_id or f"S{idx}",
                    title=doc.title,
                    url=doc.url,
                    snippet=doc.snippet,
                    excerpt=doc.excerpt,
                )
            )
        return normalized
