"""Offline worker: demonstrate execution and delivery without making web requests."""

from concurrent.futures import CancelledError
from threading import Event

from intentaware.localization import english, tr
from intentaware.contracts import DelegationResult
from intentaware.nlp.llm import FakeLLMClient

from .agent import LiveDelegator
from .models import DelegationDraft, RetrievedDocument
from .retriever import MockRetriever


DEMO_QUESTION = "如何让 argparse 的可选参数变成必填？"
_REFERENCE = RetrievedDocument(
    source_id="S1",
    title="Python documentation · argparse",
    url="https://docs.python.org/3/library/argparse.html#required",
    snippet="",
    excerpt="To make an option required, True can be specified for the required= keyword argument to add_argument():",
)


class DemoDelegator:
    def __init__(self, delay_seconds: float = 1.2, *, reference_sample: bool = False):
        if delay_seconds < 0:
            raise ValueError(tr("演示延迟不能小于零。"))
        self.delay_seconds = delay_seconds
        self.reference_sample = reference_sample

    def run(self, question: str, cancel: Event) -> DelegationResult:
        """Run an explicitly offline demonstration."""
        if not question.strip():
            raise ValueError(tr("请输入需要委托的问题。"))
        if cancel.wait(self.delay_seconds):
            raise CancelledError(tr("任务已取消。"))
        if (
            self.reference_sample
            and DelegationDraft.parse_question(question).question in (DEMO_QUESTION, english(DEMO_QUESTION))
        ):
            client = FakeLLMClient([{
                "citations": [{"source_id": _REFERENCE.source_id, "quote": _REFERENCE.excerpt}],
                "unresolved": [],
            }])
            result = LiveDelegator(client, MockRetriever([_REFERENCE])).run(question, cancel)
            return DelegationResult(
                answer=tr("离线演示 · 预置公开文档摘录\n\n{0}", result.answer),
                sources=result.sources,
            )
        return DelegationResult(
            answer=(
                tr(
                    "离线委托演示\n\n已接收问题：{0}\n\n"
                    "后台任务已经完成，主窗口在等待期间仍可继续操作。\n"
                    "本次展示后台处理和交付时机。联网委托可通过 --delegator live 启用。",
                    question.strip(),
                )
            ),
        )
