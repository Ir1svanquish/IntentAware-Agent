"""模型返回文本字段的清洗：非空、去空白、超长截断。"""

from .errors import NlpResponseError


def text_field(value: object, name: str, *, limit: int = 160) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NlpResponseError(f"模型返回的 {name} 为空或不是字符串。")
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
