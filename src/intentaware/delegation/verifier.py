"""引用核验：确认回答引用的来源编号与摘录确实存在于本次实际检索材料中。"""

from __future__ import annotations

from collections.abc import Sequence

from intentaware.localization import tr
from intentaware.contracts import Source

from .models import CitationClaim, RetrievedDocument, VerificationReport

class CitationVerifier:
    """Validate each excerpt against the fetched page body."""

    def verify(
        self,
        citations: Sequence[CitationClaim],
        documents: Sequence[RetrievedDocument],
    ) -> VerificationReport:
        by_id = {doc.source_id: doc for doc in documents[:2]}
        excerpts = {
            source_id: " ".join(doc.excerpt.split()) for source_id, doc in by_id.items()
        }
        verified_sources: list[Source] = []
        verified_ids: list[str] = []
        verified_quotes: dict[CitationClaim, None] = {}
        seen_urls: set[str] = set()
        dropped: list[str] = []

        for claim in citations:
            source_id = claim.source_id.strip()
            doc = by_id.get(source_id)
            if doc is None:
                dropped.append(tr("未知来源编号 {0}", source_id or tr("(空)")))
                continue
            quote = " ".join(claim.quote.split())
            if len(quote) < 2 or quote not in excerpts[source_id]:
                dropped.append(tr("来源 {0} 的引用摘录未能在检索原文中核实", source_id))
                continue
            verified_quotes[CitationClaim(source_id, quote)] = None
            if doc.url not in seen_urls:
                seen_urls.add(doc.url)
                verified_ids.append(source_id)
                verified_sources.append(doc.as_source())

        return VerificationReport(
            verified_sources=tuple(verified_sources),
            verified_source_ids=tuple(verified_ids),
            verified_quotes=tuple(verified_quotes),
            dropped_reasons=tuple(dropped),
            passed=bool(verified_sources),
        )
