"""接入外部模型时统一的错误类型，便于界面与测试区分失败原因。

所有消息都面向最终用户，不得包含 API 密钥。
"""


class NlpError(RuntimeError):
    """NLP 模块的基类错误。"""


class NlpConfigError(NlpError):
    """缺少服务地址、模型名或密钥等配置。"""


class NlpTimeoutError(NlpError):
    """单次请求在限定时间内没有完成。"""


class NlpTransportError(NlpError):
    """网络、鉴权、限流或服务端错误。"""


class NlpResponseError(NlpError):
    """返回内容不是约定的 JSON 结构，或字段超出允许范围。"""
