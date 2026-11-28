"""模型返回文本字段的清洗：非空、去空白、超长截断。"""

from intentaware.localization import tr
from .errors import NlpResponseError


def text_field(value: object, name: str, *, limit: int = 160) -> str:
    if not isinstance(value, str) or not value.strip():
        raise NlpResponseError(tr("模型返回的 {0} 为空或不是字符串。", name))
    text = value.strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
