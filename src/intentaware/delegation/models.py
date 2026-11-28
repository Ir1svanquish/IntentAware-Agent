"""D 模块内部数据结构：可编辑请求草稿、检索文档、引用声明与核验报告。"""

from __future__ import annotations

from dataclasses import dataclass

from intentaware.contracts import Source


@dataclass(frozen=True)
class DelegationDraft:
    raw_question: str
    question: str
    scope: str = ""
    expected_output: str = ""
    clarification_question: str = ""
    clarification_round: int = 0

    @property
    def needs_clarification(self) -> bool:
        """仅在尚未澄清且存在关键歧义时触发一次澄清。"""
        return bool(self.clarification_question.strip()) and self.clarification_round < 1

    def format_question(self) -> str:
        """将结构化请求序列化为可提交给 Delegator.run() 的文本。"""
        question = self.question.strip()
        scope = self.scope.strip()
        expected = self.expected_output.strip()
        if not scope and not expected:
            return question
        lines = [f"问题：{question}"]
        if scope:
            lines.append(f"处理范围：{scope}")
        if expected:
            lines.append(f"期望输出：{expected}")
        return "\n".join(lines)

    @classmethod
    def parse_question(cls, text: str) -> "DelegationDraft":
        """兼容纯文本问题与结构化委托请求文本。"""
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("委托问题不能为空。")

        fields: dict[str, str] = {}
        current_key: str | None = None
        prefixes = {
            "问题：": "question",
            "问题:": "question",
            "处理范围：": "scope",
            "处理范围:": "scope",
            "期望输出：": "expected_output",
            "期望输出:": "expected_output",
        }
        for raw_line in cleaned.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            matched = False
            for prefix, field_name in prefixes.items():
                if line.startswith(prefix):
                    fields[field_name] = line[len(prefix) :].strip()
                    current_key = field_name
                    matched = True
                    break
            if not matched and current_key is not None:
                prev = fields.get(current_key, "")
                fields[current_key] = f"{prev} {line}".strip()

        if "question" in fields and fields["question"]:
            return cls(
                raw_question=cleaned,
                question=fields["question"],
                scope=fields.get("scope", ""),
                expected_output=fields.get("expected_output", ""),
            )
        return cls(raw_question=cleaned, question=cleaned)


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str = ""


@dataclass(frozen=True)
class RetrievedDocument:
    source_id: str
    title: str
    url: str
    snippet: str
    excerpt: str

    def as_source(self) -> Source:
        return Source(title=self.title, url=self.url)


@dataclass(frozen=True)
class CitationClaim:
    source_id: str
    quote: str


@dataclass(frozen=True)
class VerificationReport:
    verified_sources: tuple[Source, ...]
    verified_source_ids: tuple[str, ...]
    verified_quotes: tuple[CitationClaim, ...]
    dropped_reasons: tuple[str, ...]
    passed: bool
