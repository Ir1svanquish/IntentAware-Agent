"""LLM 配置：全部来自环境变量，便于实验记录与复现。

默认值指向 DeepSeek，但任何 OpenAI 兼容端点（本地 Ollama、vLLM 等）都可以通过
``INTENTAWARE_LLM_BASE_URL`` 切换。密钥只保存在进程环境里，不写入数据目录或事件。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from intentaware.localization import tr
from .errors import NlpConfigError

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_TIMEOUT = 20.0
DEFAULT_RETRIES = 1

BASE_URL_ENV = "INTENTAWARE_LLM_BASE_URL"
API_KEY_ENV = "INTENTAWARE_LLM_API_KEY"
MODEL_ENV = "INTENTAWARE_LLM_MODEL"
TIMEOUT_ENV = "INTENTAWARE_LLM_TIMEOUT"
RETRIES_ENV = "INTENTAWARE_LLM_RETRIES"


@dataclass(frozen=True)
class LlmConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_MODEL
    timeout: float = DEFAULT_TIMEOUT
    max_retries: int = DEFAULT_RETRIES
    temperature: float = 0.0

    @property
    def endpoint(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"

    @property
    def uses_default_provider(self) -> bool:
        return self.base_url.rstrip("/") == DEFAULT_BASE_URL.rstrip("/")

    def describe(self) -> dict[str, object]:
        """写入事件的配置摘要，不含密钥。"""
        return {
            "model": self.model,
            "base_url": self.base_url,
            "temperature": self.temperature,
            "max_retries": self.max_retries,
        }

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "LlmConfig":
        values = os.environ if env is None else env
        base_url = (values.get(BASE_URL_ENV) or DEFAULT_BASE_URL).strip()
        api_key = (values.get(API_KEY_ENV) or "").strip()
        model = (values.get(MODEL_ENV) or DEFAULT_MODEL).strip()
        timeout = _number(values, TIMEOUT_ENV, DEFAULT_TIMEOUT, float, minimum=0.1)
        retries = _number(values, RETRIES_ENV, DEFAULT_RETRIES, int, minimum=0)

        if not base_url.startswith(("http://", "https://")):
            raise NlpConfigError(tr("{0} 必须是 http(s) 地址，当前为 {1!r}。", BASE_URL_ENV, base_url))
        if not model:
            raise NlpConfigError(tr("{0} 不能为空。", MODEL_ENV))

        config = cls(
            base_url=base_url,
            api_key=api_key,
            model=model,
            timeout=timeout,
            max_retries=retries,
        )
        if config.uses_default_provider and not api_key:
            raise NlpConfigError(
                tr("使用默认服务商时必须设置 {0}；如需本地模型，请同时设置 {1}。", API_KEY_ENV, BASE_URL_ENV)
            )
        return config


def _number(values: Mapping[str, str], name: str, default, cast, *, minimum: float):
    raw = (values.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise NlpConfigError(tr("{0} 必须是数字，当前为 {1!r}。", name, raw)) from None
    if value < minimum:
        raise NlpConfigError(tr("{0} 不能小于 {1:g}，当前为 {2}。", name, minimum, value))
    return value
