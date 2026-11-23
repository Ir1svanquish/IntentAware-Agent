"""只覆盖本项目 Prompt 所需子集的 JSON 结构校验。

完整 JSON Schema 实现会引入额外依赖；这里只支持 Prompt 实际用到的
``type`` / ``required`` / ``properties`` / ``items`` / ``enum`` / ``minLength``。
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

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
        raise NlpResponseError(f"{context}不符合约定结构：{error}。")


def _check(value: Any, schema: Mapping[str, Any]) -> str | None:
    expected = schema.get("type")
    if expected is not None:
        python_type = _JSON_TYPES.get(expected)
        if python_type is None:
            return f"不支持的约束类型 {expected}"
        if not isinstance(value, python_type) or (expected == "number" and isinstance(value, bool)):
            return f"应为 {expected}"

    if "enum" in schema and value not in schema["enum"]:
        return "取值不在允许范围内"

    if expected == "object":
        for name in schema.get("required", ()):
            if name not in value:
                return f"缺少字段 {name}"
        for name, child in schema.get("properties", {}).items():
            if name in value:
                error = _check(value[name], child)
                if error is not None:
                    return f"字段 {name}：{error}"

    if expected == "array" and schema.get("items") is not None:
        for index, item in enumerate(value):
            error = _check(item, schema["items"])
            if error is not None:
                return f"第 {index} 项：{error}"

    if expected == "string" and "minLength" in schema:
        if len(value.strip()) < schema["minLength"]:
            return "内容过短或为空"

    return None
