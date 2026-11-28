"""只覆盖本项目 Prompt 所需子集的 JSON 结构校验。

完整 JSON Schema 实现会引入额外依赖；这里只支持 Prompt 实际用到的
``type`` / ``required`` / ``properties`` / ``items`` / ``enum`` / ``minLength``。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from intentaware.localization import tr
from .errors import NlpResponseError

_JSON_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
}


def validate_json(value: Any, schema: Mapping[str, Any], *, context: str = "模型返回") -> None:
    error = _check(value, schema)
    if error is not None:
        raise NlpResponseError(tr("{0}不符合约定结构：{1}。", tr(context), error))


def _check(value: Any, schema: Mapping[str, Any]) -> str | None:
    expected = schema.get("type")
    if expected is not None:
        python_type = _JSON_TYPES.get(expected)
        if python_type is None:
            return tr("不支持的约束类型 {0}", expected)
        if not isinstance(value, python_type) or (expected == "number" and isinstance(value, bool)):
            return tr("应为 {0}", expected)

    if "enum" in schema and value not in schema["enum"]:
        return tr("取值不在允许范围内")

    if expected == "object":
        for name in schema.get("required", ()):
            if name not in value:
                return tr("缺少字段 {0}", name)
        for name, child in schema.get("properties", {}).items():
            if name in value:
                error = _check(value[name], child)
                if error is not None:
                    return tr("字段 {0}：{1}", name, error)

    if expected == "array" and schema.get("items") is not None:
        for index, item in enumerate(value):
            error = _check(item, schema["items"])
            if error is not None:
                return tr("第 {0} 项：{1}", index, error)

    if expected == "string" and "minLength" in schema:
        if len(value.strip()) < schema["minLength"]:
            return tr("内容过短或为空")

    return None
