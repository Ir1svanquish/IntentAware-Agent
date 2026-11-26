"""Prompt 模板的占位符、版本号与示例 JSON 契约。"""

import hashlib
import json
import re
from pathlib import Path

import pytest

from intentaware.nlp.prompts import load_prompt

PROMPT_DIR = Path(__file__).resolve().parents[1] / "src" / "intentaware" / "nlp" / "prompts"


def test_classify_prompt_exposes_stable_version_and_all_placeholders():
    prompt = load_prompt("classify_v1")
    text = (PROMPT_DIR / "classify_v1.md").read_text(encoding="utf-8")

    assert re.fullmatch(r"classify_v1@[0-9a-f]{8}", prompt.version)
    assert prompt.version.endswith(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8])
    assert load_prompt("classify_v1") is prompt  # 缓存保证同一版本

    system, user = prompt.render(
        {
            "goal_title": "完成论文",
            "goal_next_step": "整理文献",
            "progress": "已读两篇",
            "source": "用户描述",
            "activity": "正在写提纲",
        }
    )
    assert "只输出一个 JSON 对象" in system
    assert "窗口标题只说明" in system
    assert "$" not in user
    for value in ("完成论文", "整理文献", "已读两篇", "用户描述", "正在写提纲"):
        assert value in user


def test_clarify_prompt_renders_user_text_and_example_json():
    prompt = load_prompt("clarify_v1")
    system, user = prompt.render({"text": "下周三前交论文初稿"})

    assert "不要编造" in system
    assert "下周三前交论文初稿" in user
    example = re.search(r'\{"title".*\}', user)
    assert example is not None
    assert set(json.loads(example.group(0))) == {"title", "next_step", "confidence", "rationale"}


def test_missing_placeholder_is_reported_with_its_name():
    prompt = load_prompt("classify_v1")
    with pytest.raises(ValueError, match="goal_title"):
        prompt.render({"activity": "写代码"})
