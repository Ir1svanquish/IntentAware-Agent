"""D 模块配置：检索提供方、来源上限与超时参数均来自环境变量。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import os

from .errors import DelegationConfigError

DEFAULT_SEARCH_PROVIDER = "public"
VALID_SEARCH_PROVIDERS = ("public", "tavily")
DEFAULT_MAX_SOURCES = 2
DEFAULT_SEARCH_TIMEOUT = 8.0
DEFAULT_FETCH_TIMEOUT = 8.0
DEFAULT_MAX_EXCERPT_CHARS = 2500

SEARCH_PROVIDER_ENV = "INTENTAWARE_SEARCH_PROVIDER"
SEARCH_API_KEY_ENV = "INTENTAWARE_SEARCH_API_KEY"
SEARCH_BASE_URL_ENV = "INTENTAWARE_SEARCH_BASE_URL"
MAX_SOURCES_ENV = "INTENTAWARE_DELEGATION_MAX_SOURCES"
SEARCH_TIMEOUT_ENV = "INTENTAWARE_DELEGATION_SEARCH_TIMEOUT"
FETCH_TIMEOUT_ENV = "INTENTAWARE_DELEGATION_FETCH_TIMEOUT"
MAX_EXCERPT_CHARS_ENV = "INTENTAWARE_DELEGATION_MAX_EXCERPT_CHARS"


@dataclass(frozen=True)
class DelegationConfig:
    search_provider: str = DEFAULT_SEARCH_PROVIDER
    search_api_key: str = ""
    search_base_url: str = ""
    max_sources: int = DEFAULT_MAX_SOURCES
    search_timeout: float = DEFAULT_SEARCH_TIMEOUT
    fetch_timeout: float = DEFAULT_FETCH_TIMEOUT
    max_excerpt_chars: int = DEFAULT_MAX_EXCERPT_CHARS

    def describe(self) -> dict[str, object]:
        """返回写入实验事件的配置摘要，绝不包含密钥。"""
        return {
            "search_provider": self.search_provider,
            "max_sources": self.max_sources,
            "search_timeout": self.search_timeout,
            "fetch_timeout": self.fetch_timeout,
            "max_excerpt_chars": self.max_excerpt_chars,
        }

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "DelegationConfig":
        values = os.environ if env is None else env
        provider = (values.get(SEARCH_PROVIDER_ENV) or DEFAULT_SEARCH_PROVIDER).strip().lower()
        if provider not in VALID_SEARCH_PROVIDERS:
            raise DelegationConfigError(
                f"{SEARCH_PROVIDER_ENV} 必须是 {' / '.join(VALID_SEARCH_PROVIDERS)} 之一，当前为 {provider!r}。"
            )

        api_key = (values.get(SEARCH_API_KEY_ENV) or "").strip()
        base_url = (values.get(SEARCH_BASE_URL_ENV) or "").strip()
        if base_url and not base_url.startswith(("http://", "https://")):
            raise DelegationConfigError(
                f"{SEARCH_BASE_URL_ENV} 必须是 http(s) 地址，当前为 {base_url!r}。"
            )

        if provider == "tavily" and not api_key:
            raise DelegationConfigError(
                f"启用 tavily 检索时必须设置 {SEARCH_API_KEY_ENV}。"
            )

        max_sources = _number(
            values, MAX_SOURCES_ENV, DEFAULT_MAX_SOURCES, int, minimum=1, maximum=2
        )
        search_timeout = _number(
            values, SEARCH_TIMEOUT_ENV, DEFAULT_SEARCH_TIMEOUT, float, minimum=0.5
        )
        fetch_timeout = _number(
            values, FETCH_TIMEOUT_ENV, DEFAULT_FETCH_TIMEOUT, float, minimum=0.5
        )
        max_excerpt_chars = _number(
            values, MAX_EXCERPT_CHARS_ENV, DEFAULT_MAX_EXCERPT_CHARS, int, minimum=200
        )

        return cls(
            search_provider=provider,
            search_api_key=api_key,
            search_base_url=base_url,
            max_sources=max_sources,
            search_timeout=search_timeout,
            fetch_timeout=fetch_timeout,
            max_excerpt_chars=max_excerpt_chars,
        )


def _number(
    values: Mapping[str, str],
    name: str,
    default,
    cast,
    *,
    minimum: float,
    maximum: float | None = None,
):
    raw = (values.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise DelegationConfigError(f"{name} 必须是数字，当前为 {raw!r}。") from None
    if value < minimum:
        raise DelegationConfigError(f"{name} 不能小于 {minimum:g}，当前为 {value}。")
    if maximum is not None and value > maximum:
        raise DelegationConfigError(f"{name} 不能大于 {maximum:g}，当前为 {value}。")
    return value
