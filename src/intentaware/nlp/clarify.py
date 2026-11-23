"""命令行入口：把一句话目标澄清成主任务与下一步。

    python -m intentaware.nlp.clarify "下周三前交论文初稿，先补实验部分"
    python -m intentaware.nlp.clarify --json "..."

需要 ``INTENTAWARE_LLM_API_KEY``；自定义端点见 ``nlp/config.py``。
"""

from __future__ import annotations

import argparse
import json
import sys

from .config import LlmConfig
from .errors import NlpConfigError, NlpError
from .goal import LlmGoalClarifier
from .llm import OpenAICompatibleClient


def build_clarifier(env=None) -> LlmGoalClarifier:
    return LlmGoalClarifier(OpenAICompatibleClient(LlmConfig.from_env(env)))


def main(argv: list[str] | None = None, *, clarifier: LlmGoalClarifier | None = None) -> int:
    parser = argparse.ArgumentParser(description="把一句话目标澄清为主任务与下一步")
    parser.add_argument("text", nargs="+", help="一句话目标，例如：下周三前交论文初稿")
    parser.add_argument("--json", action="store_true", help="输出机器可读的 JSON")
    args = parser.parse_args(argv)

    try:
        result = (clarifier or build_clarifier()).clarify(" ".join(args.text))
    except NlpConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        return 2
    except (NlpError, ValueError) as exc:
        print(f"澄清失败：{exc}", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "title": result.title,
                    "next_step": result.next_step,
                    "confidence": result.confidence,
                    "rationale": result.rationale,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"主任务：{result.title}")
        print(f"下一步：{result.next_step}")
        print(f"置信度：{result.confidence}")
        print(f"说明：{result.rationale}")
        if result.needs_confirmation:
            print("提示：信息不足，请补充交付物、范围或时间后再采用。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
