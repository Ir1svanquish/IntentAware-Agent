"""有界公开来源检索器测试：URL 过滤、HTML 提取、DDG/Wikipedia/Tavily、超时与取消。"""

from concurrent.futures import CancelledError
import json
from threading import Event
from urllib import error as urlerror

import pytest

from intentaware.delegation import (
    DelegationConfig,
    DelegationConfigError,
    DelegationNetworkError,
    DelegationTimeoutError,
    MockRetriever,
    PublicWebRetriever,
    RetrievedDocument,
    is_public_http_url,
)
from intentaware.delegation.retriever import extract_html_text


def test_is_public_http_url_filters_private_and_local_addresses():
    assert is_public_http_url("https://docs.python.org/3/library/argparse.html")
    assert is_public_http_url("http://93.184.216.34/example")
    assert not is_public_http_url("http://localhost:8000/secret")
    assert not is_public_http_url("http://127.0.0.1:8080")
    assert not is_public_http_url("http://192.168.1.10/admin")
    assert not is_public_http_url("http://10.0.0.1/internal")
    assert not is_public_http_url("http://intranet/docs")
    assert not is_public_http_url("file:///etc/passwd")
    assert not is_public_http_url("https://user:pass@example.com/private")


def test_extract_html_text_strips_scripts_and_truncates():
    html = """
    <html>
      <head><title>Argparse Docs</title><style>body { color: red; }</style></head>
      <body>
        <script>console.log("ignore me");</script>
        <h1>Command-Line Parsing</h1>
        <p>Use required=True on add_argument for required options.</p>
      </body>
    </html>
    """
    title, body = extract_html_text(html, max_chars=45)
    assert title == "Argparse Docs"
    assert "ignore me" not in body
    assert "color: red" not in body
    assert len(body) <= 45


def test_public_retriever_duckduckgo_unwraps_urls_and_caps_at_two():
    ddg_html = """
    <html><body>
      <a class="result__a" href="http://127.0.0.1/private">Local Leak</a>
      <a class="result__snippet">Should be skipped</a>
      <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3%2Flibrary%2Fargparse.html">Python argparse</a>
      <a class="result__snippet">Parser for command-line options.</a>
      <a class="result__a" href="https://realpython.com/command-line-interfaces-python-argparse/">Real Python argparse</a>
      <a class="result__snippet">Guide for Python CLI tools.</a>
      <a class="result__a" href="https://example.org/third">Third Result</a>
      <a class="result__snippet">Must not be fetched.</a>
    </body></html>
    """.encode("utf-8")

    fetched_urls = []

    def fake_get(url, headers, timeout):
        fetched_urls.append(url)
        if "html.duckduckgo.com" in url:
            return ddg_html, "text/html"
        if "docs.python.org" in url:
            return b"<html><title>argparse</title><body><p>Set required=True in add_argument.</p></body></html>", "text/html"
        if "realpython.com" in url:
            return b"<html><title>RealPython</title><body><p>Use required=True for mandatory flags.</p></body></html>", "text/html"
        raise AssertionError(f"Unexpected fetch beyond 2 sources: {url}")

    retriever = PublicWebRetriever(DelegationConfig(), http_get=fake_get)
    docs = retriever.retrieve("python argparse required", max_sources=5)

    assert len(docs) == 2
    assert [doc.source_id for doc in docs] == ["S1", "S2"]
    assert docs[0].url == "https://docs.python.org/3/library/argparse.html"
    assert "required=True" in docs[0].excerpt
    assert "http://127.0.0.1/private" not in fetched_urls
    assert "https://example.org/third" not in fetched_urls


def test_public_retriever_falls_back_to_wikipedia_and_uses_snippet_if_page_blocked():
    wiki_json = json.dumps(
        {
            "query": {
                "search": [
                    {
                        "title": "WAL模式",
                        "snippet": "SQLite 的 <span class=\"searchmatch\">WAL</span> 模式支持读写并发。",
                    }
                ]
            }
        }
    ).encode("utf-8")

    def fake_get(url, headers, timeout):
        if "html.duckduckgo.com" in url:
            raise urlerror.URLError("ddg blocked")
        if "zh.wikipedia.org/w/api.php" in url:
            return wiki_json, "application/json"
        if "zh.wikipedia.org/wiki/" in url:
            raise urlerror.HTTPError(url, 403, "Forbidden", {}, None)
        raise AssertionError(f"Unexpected URL: {url}")

    retriever = PublicWebRetriever(DelegationConfig(), http_get=fake_get)
    docs = retriever.retrieve("SQLite WAL 模式")

    assert len(docs) == 1
    assert docs[0].source_id == "S1"
    assert "zh.wikipedia.org/wiki/" in docs[0].url
    assert "读写并发" in docs[0].excerpt


def test_public_retriever_raises_timeout_when_all_providers_timeout():
    def timeout_get(url, headers, timeout):
        raise TimeoutError("timed out")

    retriever = PublicWebRetriever(
        DelegationConfig(search_timeout=1.5),
        http_get=timeout_get,
    )
    with pytest.raises(DelegationTimeoutError):
        retriever.retrieve("carryover effect")


def test_tavily_config_and_search_provider():
    with pytest.raises(DelegationConfigError):
        DelegationConfig.from_env({"INTENTAWARE_SEARCH_PROVIDER": "tavily"})

    cfg = DelegationConfig.from_env(
        {"INTENTAWARE_SEARCH_PROVIDER": "tavily", "INTENTAWARE_SEARCH_API_KEY": "tvly-secret"}
    )
    assert "tvly-secret" not in str(cfg.describe())

    def fake_post(url, payload, headers, timeout):
        assert payload["api_key"] == "tvly-secret"
        return json.dumps(
            {
                "results": [
                    {
                        "title": "Carryover Effect",
                        "url": "https://example.org/carryover",
                        "content": "Within-subjects designs face carryover effects across conditions.",
                    }
                ]
            }
        ).encode("utf-8")

    def fake_get(url, headers, timeout):
        return b"<html><body><p>Counterbalancing mitigates carryover effects.</p></body></html>", "text/html"

    retriever = PublicWebRetriever(cfg, http_get=fake_get, http_post_json=fake_post)
    docs = retriever.retrieve("carryover effect")
    assert len(docs) == 1
    assert docs[0].url == "https://example.org/carryover"
    assert "Counterbalancing" in docs[0].excerpt


def test_retriever_honors_cancel_signal():
    cancel = Event()
    cancel.set()

    def should_not_run(url, headers, timeout):
        raise AssertionError("cancel=True 时不应发起网络请求")

    retriever = PublicWebRetriever(DelegationConfig(), http_get=should_not_run)
    with pytest.raises(CancelledError):
        retriever.retrieve("Macro-F1", cancel=cancel)

    mock = MockRetriever([RetrievedDocument("S1", "Title", "https://example.org", "s", "e")])
    with pytest.raises(CancelledError):
        mock.retrieve("Macro-F1", cancel=cancel)


def test_redirect_handler_blocks_non_public_targets():
    from urllib import request as urlrequest
    from intentaware.delegation.retriever import _PublicRedirectHandler

    handler = _PublicRedirectHandler()
    req = urlrequest.Request("https://example.org/start")

    with pytest.raises(urlerror.URLError):
        handler.redirect_request(req, None, 302, "Found", {}, "http://127.0.0.1/secret")

    with pytest.raises(urlerror.URLError):
        handler.redirect_request(req, None, 302, "Found", {}, "//localhost:8080/internal")

    allowed = handler.redirect_request(req, None, 302, "Found", {}, "https://docs.python.org/3/")
    assert allowed.full_url == "https://docs.python.org/3/"


def test_ddg_parser_preserves_nested_tags_inside_snippet():
    from intentaware.delegation.retriever import _DuckDuckGoParser

    parser = _DuckDuckGoParser()
    parser.feed(
        """
        <div class="result">
          <a class="result__a" href="https://docs.python.org/3/library/argparse.html">
            <b>argparse</b> — Parser for command-line options
          </a>
          <div class="result__snippet">
            Use <b>required=True</b> inside <span class="kw">add_argument</span> for mandatory flags.
          </div>
        </div>
        """
    )
    parser.close()
    assert len(parser.hits) == 1
    assert "Parser for command-line options" in parser.hits[0].title
    assert "for mandatory flags." in parser.hits[0].snippet
