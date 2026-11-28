"""OpenAI 兼容的对话补全客户端，只依赖标准库。

模块只负责一次「发 Prompt、取 JSON」的往返：超时、有限重试、错误分类与结构校验
都在这里完成；业务字段（例如分类标签）由调用方再校验一次，便于替换客户端实现。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import json
import socket
import time
from typing import Protocol
from urllib import error as urlerror
from urllib import request as urlrequest

from intentaware.localization import tr
from .config import API_KEY_ENV, LlmConfig
from .errors import NlpConfigError, NlpResponseError, NlpTimeoutError, NlpTransportError
from .schema import validate_json

Transport = Callable[[str, dict, dict, float], bytes]


class LLMClient(Protocol):
    """最小客户端协议：测试与本地演示可以替换成任意实现。"""

    model: str

    def complete_json(
        self, *, system: str, user: str, schema: Mapping[str, object]
    ) -> dict:
        """返回已通过结构校验的 JSON 对象；失败时抛出 ``NlpError``。"""
        ...


class OpenAICompatibleClient:
    """把 Prompt 发给任意 OpenAI 兼容端点，并解析 JSON 结果。"""

    def __init__(
        self,
        config: LlmConfig,
        *,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.model = config.model
        self._transport = transport or _post_json
        self._sleep = sleep
        # 当前调用收到的用量与耗时，供实验报告使用。
        self.last_usage: dict[str, int] = {}
        self.last_latency_ms: float | None = None

    def complete_json(
        self, *, system: str, user: str, schema: Mapping[str, object]
    ) -> dict:
        self.last_usage = {}
        self.last_latency_ms = None
        content = self._request(system, user)
        data = _decode_content(content)
        validate_json(data, schema, context=tr("模型返回"))
        return data

    def _request(self, system: str, user: str) -> str:
        payload = {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = self._headers()
        attempts = self.config.max_retries + 1

        for attempt in range(1, attempts + 1):
            try:
                started = time.perf_counter()
                raw = self._transport(
                    self.config.endpoint, payload, headers, self.config.timeout
                )
                latency_ms = (time.perf_counter() - started) * 1000
                content, usage = _message_content(raw)
                self.last_usage = usage
                self.last_latency_ms = latency_ms
                return content
            except urlerror.HTTPError as exc:
                retryable = exc.code == 429 or 500 <= exc.code < 600
                if retryable and attempt < attempts:
                    self._sleep(_backoff(attempt))
                    continue
                if exc.code in (401, 403):
                    raise NlpTransportError(
                        tr("模型服务鉴权失败（HTTP {0}），请检查 {1}。", exc.code, API_KEY_ENV)
                    ) from None
                raise NlpTransportError(tr("模型服务返回 HTTP {0}。", exc.code)) from None
            except (urlerror.URLError, TimeoutError, socket.timeout) as exc:
                if attempt < attempts:
                    self._sleep(_backoff(attempt))
                    continue
                if _is_timeout(exc):
                    raise NlpTimeoutError(
                        tr("模型服务在 {0:g} 秒内没有响应。", self.config.timeout)
                    ) from None
                raise NlpTransportError(
                    tr("无法连接模型服务，请检查网络或 INTENTAWARE_LLM_BASE_URL。")
                ) from None

        raise NlpTransportError(tr("模型请求失败：重试次数已用尽。"))  # pragma: no cover

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.config.api_key:
            headers["Authorization"] = f"Bearer {self.config.api_key}"
        return headers


class FakeLLMClient:
    """按顺序返回预设结果，供离线测试与演示使用。"""

    def __init__(self, responses: Iterable[object] = (), *, model: str = "fake-model"):
        self.model = model
        self.responses = list(responses)
        self.calls: list[dict] = []

    def complete_json(
        self, *, system: str, user: str, schema: Mapping[str, object]
    ) -> dict:
        self.calls.append({"system": system, "user": user, "schema": schema})
        if not self.responses:
            raise AssertionError(tr("FakeLLMClient 没有剩余预设响应。"))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        if not isinstance(response, dict):
            raise AssertionError(tr("FakeLLMClient 的预设响应必须是字典。"))
        return response


def _post_json(url: str, payload: dict, headers: dict, timeout: float) -> bytes:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urlrequest.Request(url, data=body, headers=headers, method="POST")
    with urlrequest.urlopen(request, timeout=timeout) as response:
        return response.read()


def _message_content(raw: bytes) -> tuple[str, dict[str, int]]:
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise NlpResponseError(tr("模型服务没有返回 JSON 响应。")) from None
    if not isinstance(body, dict):
        raise NlpResponseError(tr("模型服务返回了非对象 JSON。"))

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise NlpResponseError(tr("模型服务返回中没有 choices。"))
    first = choices[0]
    message = first.get("message") if isinstance(first, dict) else None
    content = message.get("content") if isinstance(message, dict) else None
    usage = _usage(body.get("usage"))
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False), usage
    if not isinstance(content, str) or not content.strip():
        raise NlpResponseError(tr("模型返回内容为空。"))
    return content, usage


def _usage(raw: object) -> dict[str, int]:
    """只保留整数计数字段；不同服务商的 usage 结构可能多出嵌套对象。"""
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): value
        for key, value in raw.items()
        if isinstance(value, int) and not isinstance(value, bool)
    }


def _decode_content(content: str) -> dict:
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        raise NlpResponseError(tr("模型返回的不是合法 JSON，可能被截断或包含额外说明。")) from None
    if not isinstance(data, dict):
        raise NlpResponseError(tr("模型返回的 JSON 顶层必须是对象。"))
    return data


def _is_timeout(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, (TimeoutError, socket.timeout))


def _backoff(attempt: int) -> float:
    return 0.5 * 2 ** (attempt - 1)


__all__ = [
    "FakeLLMClient",
    "LLMClient",
    "NlpConfigError",
    "OpenAICompatibleClient",
]
