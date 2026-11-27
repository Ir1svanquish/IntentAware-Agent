"""引用核验：确认回答引用的来源编号与摘录确实存在于本次实际检索材料中。"""

from __future__ import annotations

from collections.abc import Sequence
import re

from intentaware.contracts import Source

from .models import CitationClaim, RetrievedDocument, VerificationReport

_SPACE_RE = re.compile(r"\s+")
_PUNCT_RE = re.compile(r"[^\w\u4e00-\u9fff]+")
_ASCII_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_CJK_CHAR_RE = re.compile(r"[\u4e00-\u9fff]")


def _compact(text: str) -> str:
    return _PUNCT_RE.sub("", text.lower())


def _support_tokens(text: str) -> list[str]:
    lowered = text.lower()
    tokens: list[str] = _ASCII_TOKEN_RE.findall(lowered)
    cjk_chars = _CJK_CHAR_RE.findall(lowered)
    if len(cjk_chars) >= 2:
        tokens.extend(cjk_chars[i] + cjk_chars[i + 1] for i in range(len(cjk_chars) - 1))
    elif cjk_chars:
        tokens.extend(cjk_chars)
    return tokens


def _quote_supported(quote: str, doc: RetrievedDocument) -> bool:
    cleaned = _SPACE_RE.sub(" ", quote).strip()
    if not cleaned:
        return False
    corpus = f"{doc.title}\n{doc.snippet}\n{doc.excerpt}"
    compact_quote = _compact(cleaned)
    compact_corpus = _compact(corpus)
    if len(compact_quote) >= 2 and compact_quote in compact_corpus:
        return True

    tokens = _support_tokens(cleaned)
    if not tokens:
        return False
    corpus_lower = corpus.lower()
    matched = sum(1 for token in tokens if token in corpus_lower)
    return (matched / len(tokens)) >= 0.45


class CitationVerifier:
    """白名单 + 原文支撑度校验器，防止模型编造 URL 或未检索过的依据。"""

    def verify(
        self,
        citations: Sequence[CitationClaim],
        documents: Sequence[RetrievedDocument],
    ) -> VerificationReport:
        by_id = {doc.source_id: doc for doc in documents[:2]}
        verified_sources: list[Source] = []
        verified_ids: list[str] = []
        seen_urls: set[str] = set()
        dropped: list[str] = []

        for claim in citations:
            source_id = claim.source_id.strip()
            doc = by_id.get(source_id)
            if doc is None:
                dropped.append(f"未知来源编号 {source_id or '(空)'}")
                continue
            if not _quote_supported(claim.quote, doc):
                dropped.append(f"来源 {source_id} 的引用摘录未能在检索原文中核实")
                continue
            if doc.url in seen_urls or len(verified_sources) >= 2:
                continue
            seen_urls.add(doc.url)
            verified_ids.append(source_id)
            verified_sources.append(doc.as_source())

        return VerificationReport(
            verified_sources=tuple(verified_sources),
            verified_source_ids=tuple(verified_ids),
            dropped_reasons=tuple(dropped),
            passed=bool(verified_sources),
        )
