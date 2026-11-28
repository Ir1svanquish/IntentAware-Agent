"""加载委托模块 Prompt 模板并生成内容哈希版本号。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from string import Template

_PROMPT_DIR = Path(__file__).with_name("prompts")
_SECTIONS = ("system", "user")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    system: str
    user_template: str

    def render(self, values: Mapping[str, str]) -> tuple[str, str]:
        """返回 (system, user)；缺少占位符时给出明确错误。"""
        try:
            user = Template(self.user_template).substitute(
                {key: str(value) for key, value in values.items()}
            )
        except KeyError as exc:
            raise ValueError(f"Prompt {self.name} 缺少占位符：{exc.args[0]}") from None
        return self.system, user


@lru_cache(maxsize=None)
def load_prompt(name: str) -> Prompt:
    path = _PROMPT_DIR / f"{name}.md"
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise FileNotFoundError(f"找不到 Prompt 模板：{path}") from None

    sections = _split_sections(text)
    missing = [section for section in _SECTIONS if not sections.get(section)]
    if missing:
        raise ValueError(f"Prompt {name} 缺少段落：{', '.join(missing)}")

    digest = sha256(text.encode("utf-8")).hexdigest()[:8]
    return Prompt(
        name=name,
        version=f"{name}@{digest}",
        system=sections["system"],
        user_template=sections["user"],
    )


def _split_sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("## "):
            current = line[3:].strip()
            sections.setdefault(current, [])
            continue
        if current is not None:
            sections[current].append(line)
    return {name: "\n".join(lines).strip() for name, lines in sections.items()}
