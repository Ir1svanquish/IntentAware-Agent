"""LiveDelegator 端到端离线测试：正常流程、异常拦截、并发指标隔离、I/D 交付与事件检查。"""

from concurrent.futures import CancelledError
import time
from threading import Event

import pytest

from experiments.check_events import check_events
from intentaware.contracts import Condition, JobStatus
from intentaware.delegation import (
    DelegationConfig,
    DelegationRetrievalError,
    DelegationTimeoutError,
    DelegationVerificationError,
    LiveDelegator,
    MockRetriever,
    RetrievedDocument,
)
from intentaware.localization import get_language, set_language
from intentaware.memory.store import SQLiteStore
from intentaware.nlp.errors import NlpTimeoutError
from intentaware.nlp.llm import FakeLLMClient
from intentaware.session import DesktopSession


def _sample_docs():
    return [
        RetrievedDocument(
            source_id="S1",
            title="Python argparse 官方文档",
            url="https://docs.python.org/3/library/argparse.html",
            snippet="add_argument 支持 required=True",
            excerpt="在 argparse 中，为可选参数传入 required=True 即可强制要求用户提供该参数。",
        ),
        RetrievedDocument(
            source_id="S2",
            title="Python CLI 参数最佳实践",
            url="https://example.org/cli-guide",
            snippet="位置参数默认必填",
            excerpt="位置参数（不带短横线前缀）默认就是必填参数，无需再设置 required。",
        ),
    ]


def test_live_delegator_produces_verified_answer_and_unresolved_points():
    llm = FakeLLMClient(
        [
            {
                "answer": "模型生成的未核验文本不得出现在答案中。",
                "citations": [
                    {"source_id": "S1", "quote": "传入 required=True 即可强制要求用户提供该参数"},
                    {"source_id": "S2", "quote": "位置参数（不带短横线前缀）默认就是必填参数"},
                ],
                "unresolved": ["未对比子命令 subparsers 的互斥必填校验。"],
            }
        ]
    )
    delegator = LiveDelegator(llm, MockRetriever(_sample_docs()), config=DelegationConfig())
    result, metrics = delegator.run_with_metrics(
        "问题：Python 的 argparse 怎么设置必填参数？\n处理范围：仅看官方用法", Event()
    )

    assert "required=True" in result.answer
    assert "未解决的部分" in result.answer
    assert "subparsers" in result.answer
    assert "未核验文本" not in result.answer
    assert len(result.sources) == 2
    assert result.sources[0].url == "https://docs.python.org/3/library/argparse.html"
    assert metrics["sources_count"] == 2
    assert isinstance(metrics["latency_ms"], float)


def test_english_delivery_keeps_verified_quotations_in_the_source_language():
    quote = "传入 required=True 即可强制要求用户提供该参数"
    client = FakeLLMClient([{
        "citations": [{"source_id": "S1", "quote": quote}],
        "unresolved": ["Subcommands were outside the scope."],
    }])
    delegator = LiveDelegator(client, MockRetriever(_sample_docs()))
    previous = get_language()
    set_language("en")
    try:
        result = delegator.run(
            "Question: How do I make an argparse flag required?\nScope: Check official documentation", Event(),
        )
    finally:
        set_language(previous)

    assert "Write all user-facing feedback in English" in client.calls[0]["system"]
    assert "Verified excerpts" in result.answer
    assert quote in result.answer
    assert "Open questions" in result.answer
    assert "Subcommands were outside the scope." in result.answer


def test_live_delegator_blocks_empty_retrieval_and_unverified_citations():
    empty_delegator = LiveDelegator(FakeLLMClient([]), MockRetriever([]))
    with pytest.raises(DelegationRetrievalError):
        empty_delegator.run("找不到公开来源的问题", Event())

    hallucinating = FakeLLMClient(
        [
            {
                "answer": "这是模型自己编造的结论。",
                "citations": [{"source_id": "S9", "quote": "不存在的来源"}],
                "unresolved": [],
            }
        ]
    )
    delegator = LiveDelegator(hallucinating, MockRetriever(_sample_docs()))
    with pytest.raises(DelegationVerificationError):
        delegator.run("Python argparse 怎么用？", Event())


def test_live_delegator_translates_timeout_and_honors_cancel():
    timeout_delegator = LiveDelegator(
        FakeLLMClient([NlpTimeoutError("请求超时")]),
        MockRetriever(_sample_docs()),
    )
    with pytest.raises(DelegationTimeoutError):
        timeout_delegator.run("Python argparse 怎么用？", Event())

    cancel = Event()
    cancel.set()
    with pytest.raises(CancelledError):
        LiveDelegator(FakeLLMClient([]), MockRetriever(_sample_docs())).run("问题", cancel)


def test_live_delegator_in_session_conditions_and_event_checker(tmp_path):
    def client_factory():
        return FakeLLMClient(
            [
                {
                    "answer": "通过 required=True 或位置参数设置必填。",
                    "citations": [{"source_id": "S1", "quote": "传入 required=True"}],
                    "unresolved": ["未验证 Python 3.8 旧版本差异"],
                }
            ]
        )

    delegator = LiveDelegator(client_factory, MockRetriever(_sample_docs()))
    session = DesktopSession(SQLiteStore(tmp_path / "live.sqlite3"), delegator=delegator, condition=Condition.D)
    try:
        session.set_goal("完善 CLI 工具", "补全参数校验")
        job1 = session.submit_delegation("Python argparse 怎么设置必填参数？")
        job2 = session.submit_delegation("如何设置位置参数？")

        deadline = time.monotonic() + 3
        while any(j.status == JobStatus.RUNNING for j in (job1, job2)) and time.monotonic() < deadline:
            session.poll()
            time.sleep(0.01)

        assert job1.status == JobStatus.READY
        assert job2.status == JobStatus.READY

        session.reveal_job(job1.id)
        assert job1.status == JobStatus.DELIVERED
        assert len(job1.result.sources) == 1

        delivered = session.checkpoint("写完 CLI 解析函数")
        assert delivered == 1
        assert job2.status == JobStatus.DELIVERED

        events_path = tmp_path / "events.jsonl"
        session.export_events(events_path)
        report = check_events(events_path)
        assert report.error_count == 0
        assert report.warning_count == 0
        completed_events = [e for e in session.events if e.name == "delegation_completed"]
        assert len(completed_events) == 2
        assert all(e.details.get("sources_count") == 1 for e in completed_events)
    finally:
        session.close()


def test_live_delegator_translates_malformed_payload():
    from intentaware.delegation import DelegationError

    bad_llm = FakeLLMClient(
        [
            {
                "citations": "required=True",
                "unresolved": [],
            }
        ]
    )
    delegator = LiveDelegator(bad_llm, MockRetriever(_sample_docs()))
    with pytest.raises(DelegationError):
        delegator.run("Python argparse 怎么设置必填参数？", Event())


def test_same_question_keeps_metrics_by_job_when_results_finish_out_of_order(tmp_path):
    first_started, release_first = Event(), Event()

    class Client:
        def __init__(self, tokens):
            self.last_usage = {"total_tokens": tokens}

        def complete_json(self, **kwargs):
            if self.last_usage["total_tokens"] == 11:
                first_started.set()
                assert release_first.wait(4)
            return {"citations": [{"source_id": "S1", "quote": "传入 required=True"}], "unresolved": []}

    clients = iter([Client(11), Client(22)])
    delegator = LiveDelegator(lambda: next(clients), MockRetriever(_sample_docs()))
    session = DesktopSession(SQLiteStore(tmp_path / "concurrent.sqlite3"), delegator=delegator)
    try:
        session.set_goal("完成报告", "核对内容")
        first = session.submit_delegation("重复问题")
        assert first_started.wait(2)
        second = session.submit_delegation("重复问题")
        session._pending[second.id][0].result(timeout=2)
        release_first.set()
        session._pending[first.id][0].result(timeout=2)
        session.poll()
        usage = {e.job_id: e.details["usage"]["total_tokens"]
                 for e in session.events if e.name == "delegation_completed"}
        assert usage == {first.id: 11, second.id: 22}
    finally:
        release_first.set()
        session.close()
