"""引用核验测试：白名单校验、原文支撑核对、去重与拦截幻觉引用。"""

from intentaware.delegation import CitationClaim, CitationVerifier, RetrievedDocument


def _docs():
    return [
        RetrievedDocument(
            source_id="S1",
            title="Python argparse documentation",
            url="https://docs.python.org/3/library/argparse.html",
            snippet="Command-line argument parsing",
            excerpt="The add_argument method accepts required=True to mark a flag as mandatory.",
        ),
        RetrievedDocument(
            source_id="S2",
            title="SQLite WAL 模式",
            url="https://zh.wikipedia.org/wiki/SQLite",
            snippet="WAL 支持并发读写",
            excerpt="Write-Ahead Logging 模式下，读操作不会阻塞写操作，写操作也不会阻塞读操作。",
        ),
    ]


def test_verifier_accepts_supported_citations_and_deduplicates():
    verifier = CitationVerifier()
    report = verifier.verify(
        [
            CitationClaim("S1", "add_argument method accepts required=True"),
            CitationClaim("S1", "mark a flag as mandatory"),
            CitationClaim("S2", "读操作不会阻塞写操作"),
        ],
        _docs(),
    )
    assert report.passed is True
    assert len(report.verified_sources) == 2
    assert report.verified_source_ids == ("S1", "S2")
    assert report.dropped_reasons == ()


def test_verifier_drops_unknown_source_and_fabricated_quote():
    verifier = CitationVerifier()
    report = verifier.verify(
        [
            CitationClaim("S99", "https://fake.example.com"),
            CitationClaim("S1", "Completely unrelated quantum computing claim"),
            CitationClaim("S2", "写操作也不会阻塞读操作"),
        ],
        _docs(),
    )
    assert report.passed is True
    assert len(report.verified_sources) == 1
    assert report.verified_sources[0].url == "https://zh.wikipedia.org/wiki/SQLite"
    assert len(report.dropped_reasons) == 2


def test_verifier_fails_when_no_citation_is_supported():
    verifier = CitationVerifier()
    report = verifier.verify(
        [CitationClaim("S3", "not retrieved"), CitationClaim("S1", "fabricated text")],
        _docs(),
    )
    assert report.passed is False
    assert report.verified_sources == ()
