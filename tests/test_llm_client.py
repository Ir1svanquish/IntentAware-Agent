"""LLM 客户端的请求结构、重试与错误分类，全部离线运行。"""

import json
import socket
from urllib import error as urlerror

import pytest

from intentaware.nlp.config import LlmConfig
from intentaware.nlp.errors import (
    NlpConfigError,
    NlpResponseError,
    NlpTimeoutError,
    NlpTransportError,
)
from intentaware.nlp.llm import FakeLLMClient, OpenAICompatibleClient

SCHEMA = {
    "type": "object",
    "required": ["label"],
    "properties": {"label": {"type": "string", "enum": ["a", "b"]}},
}


def response_body(content) -> bytes:
    if not isinstance(content, str):
        content = json.dumps(content, ensure_ascii=False)
    return json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": content}}]},
        ensure_ascii=False,
    ).encode("utf-8")


class Recorder:
    """记录每次传输参数，并按顺序返回预设结果或抛出预设异常。"""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def __call__(self, url, payload, headers, timeout):
        self.calls.append({"url": url, "payload": payload, "headers": headers, "timeout": timeout})
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def make_client(recorder, **overrides):
    sleeps = []
    config = LlmConfig(
        base_url="https://example.test/v1",
        api_key="sk-test-secret",
        model="test-model",
        **overrides,
    )
    client = OpenAICompatibleClient(config, transport=recorder, sleep=sleeps.append)
    return client, sleeps


def test_request_uses_openai_compatible_payload_and_bearer_token():
    recorder = Recorder(response_body({"label": "a"}))
    client, _ = make_client(recorder, timeout=9.5)

    result = client.complete_json(system="系统提示", user="用户输入", schema=SCHEMA)

    assert result == {"label": "a"}
    call = recorder.calls[0]
    assert call["url"] == "https://example.test/v1/chat/completions"
    assert call["timeout"] == 9.5
    assert call["headers"]["Authorization"] == "Bearer sk-test-secret"
    assert call["payload"]["model"] == "test-model"
    assert call["payload"]["temperature"] == 0.0
    assert call["payload"]["response_format"] == {"type": "json_object"}
    assert call["payload"]["messages"] == [
        {"role": "system", "content": "系统提示"},
        {"role": "user", "content": "用户输入"},
    ]


def test_content_can_be_a_json_object_instead_of_a_string():
    raw = json.dumps(
        {"choices": [{"message": {"content": {"label": "b"}}}]}
    ).encode("utf-8")
    client, _ = make_client(Recorder(raw))

    assert client.complete_json(system="s", user="u", schema=SCHEMA) == {"label": "b"}


def test_auth_failure_is_not_retried_and_never_leaks_the_key():
    recorder = Recorder(urlerror.HTTPError("https://example.test", 401, "Unauthorized", {}, None))
    client, sleeps = make_client(recorder)

    with pytest.raises(NlpTransportError) as excinfo:
        client.complete_json(system="s", user="u", schema=SCHEMA)

    assert "401" in str(excinfo.value)
    assert "sk-test-secret" not in str(excinfo.value)
    assert len(recorder.calls) == 1
    assert sleeps == []


def test_server_error_is_retried_once_before_success():
    recorder = Recorder(
        urlerror.HTTPError("https://example.test", 503, "Unavailable", {}, None),
        response_body({"label": "a"}),
    )
    client, sleeps = make_client(recorder, max_retries=1)

    assert client.complete_json(system="s", user="u", schema=SCHEMA) == {"label": "a"}
    assert len(recorder.calls) == 2
    assert sleeps == [0.5]


def test_server_error_stops_after_retry_budget():
    recorder = Recorder(
        urlerror.HTTPError("https://example.test", 500, "Boom", {}, None),
        urlerror.HTTPError("https://example.test", 500, "Boom", {}, None),
    )
    client, sleeps = make_client(recorder, max_retries=1)

    with pytest.raises(NlpTransportError):
        client.complete_json(system="s", user="u", schema=SCHEMA)

    assert len(recorder.calls) == 2
    assert sleeps == [0.5]


def test_timeout_is_retried_then_reported_as_timeout():
    recorder = Recorder(
        urlerror.URLError(socket.timeout("timed out")),
        response_body({"label": "b"}),
    )
    client, _ = make_client(recorder, max_retries=1)
    assert client.complete_json(system="s", user="u", schema=SCHEMA) == {"label": "b"}

    exhausted = Recorder(
        urlerror.URLError(socket.timeout("timed out")),
        urlerror.URLError(socket.timeout("timed out")),
    )
    client, _ = make_client(exhausted, max_retries=1)
    with pytest.raises(NlpTimeoutError):
        client.complete_json(system="s", user="u", schema=SCHEMA)


def test_network_error_is_transport_not_timeout():
    recorder = Recorder(urlerror.URLError(ConnectionRefusedError("refused")))
    client, _ = make_client(recorder, max_retries=0)

    with pytest.raises(NlpTransportError):
        client.complete_json(system="s", user="u", schema=SCHEMA)


@pytest.mark.parametrize(
    "raw",
    [
        b"not json",
        json.dumps({"choices": []}).encode(),
        json.dumps({"choices": [{"message": {"content": ""}}]}).encode(),
    ],
)
def test_malformed_service_responses_raise_response_error(raw):
    client, _ = make_client(Recorder(raw))
    with pytest.raises(NlpResponseError):
        client.complete_json(system="s", user="u", schema=SCHEMA)


def test_non_json_content_and_schema_violation_raise_response_error():
    client, _ = make_client(Recorder(response_body("这是一段解释，不是 JSON")))
    with pytest.raises(NlpResponseError):
        client.complete_json(system="s", user="u", schema=SCHEMA)

    client, _ = make_client(Recorder(response_body({"label": "c"})))
    with pytest.raises(NlpResponseError):
        client.complete_json(system="s", user="u", schema=SCHEMA)


def test_missing_api_key_omits_authorization_header_for_custom_endpoint():
    config = LlmConfig(base_url="http://127.0.0.1:11434/v1", api_key="", model="local-model")
    recorder = Recorder(response_body({"label": "a"}))
    client = OpenAICompatibleClient(config, transport=recorder, sleep=lambda _: None)

    client.complete_json(system="s", user="u", schema=SCHEMA)
    assert "Authorization" not in recorder.calls[0]["headers"]


def test_config_from_env_defaults_and_validation():
    config = LlmConfig.from_env({"INTENTAWARE_LLM_API_KEY": "sk-x"})
    assert config.base_url == "https://api.deepseek.com/v1"
    assert config.model == "deepseek-chat"
    assert config.endpoint.endswith("/chat/completions")

    with pytest.raises(NlpConfigError, match="INTENTAWARE_LLM_API_KEY"):
        LlmConfig.from_env({})

    local = LlmConfig.from_env({"INTENTAWARE_LLM_BASE_URL": "http://127.0.0.1:8080/v1"})
    assert local.uses_default_provider is False

    with pytest.raises(NlpConfigError, match="http"):
        LlmConfig.from_env({"INTENTAWARE_LLM_BASE_URL": "example.test"})

    with pytest.raises(NlpConfigError, match="TIMEOUT"):
        LlmConfig.from_env(
            {"INTENTAWARE_LLM_API_KEY": "sk-x", "INTENTAWARE_LLM_TIMEOUT": "soon"}
        )


def test_fake_client_pops_queued_responses_and_records_prompts():
    client = FakeLLMClient([{"label": "a"}, RuntimeError("boom")])

    assert client.complete_json(system="s", user="u", schema=SCHEMA) == {"label": "a"}
    with pytest.raises(RuntimeError):
        client.complete_json(system="s", user="u", schema=SCHEMA)
    assert [call["user"] for call in client.calls] == ["u", "u"]

    with pytest.raises(AssertionError):
        client.complete_json(system="s", user="u", schema=SCHEMA)


def test_usage_and_latency_are_exposed_for_reporting():
    body = json.dumps(
        {
            "choices": [{"message": {"content": json.dumps({"label": "a"})}}],
            "usage": {
                "prompt_tokens": 123,
                "completion_tokens": 7,
                "total_tokens": 130,
                "details": {"cached_tokens": 5},
            },
        }
    ).encode("utf-8")
    client, _ = make_client(Recorder(body))

    assert client.last_usage == {}
    assert client.last_latency_ms is None

    client.complete_json(system="s", user="u", schema=SCHEMA)

    assert client.last_usage == {
        "prompt_tokens": 123,
        "completion_tokens": 7,
        "total_tokens": 130,
    }
    assert client.last_latency_ms is not None
    assert client.last_latency_ms >= 0


def test_missing_usage_is_reported_as_empty_not_an_error():
    client, _ = make_client(Recorder(response_body({"label": "b"})))

    assert client.complete_json(system="s", user="u", schema=SCHEMA) == {"label": "b"}
    assert client.last_usage == {}
    assert client.last_latency_ms is not None
