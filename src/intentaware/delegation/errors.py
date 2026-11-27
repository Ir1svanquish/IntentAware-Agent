"""异步委托模块异常体系。"""


class DelegationError(RuntimeError):
    """委托处理中的可预期失败基类。"""


class DelegationConfigError(DelegationError):
    """缺少环境变量或检索/超时配置非法。"""


class DelegationTimeoutError(DelegationError):
    """外部检索或模型请求超过有限超时时间。"""


class DelegationNetworkError(DelegationError):
    """外部检索或模型网络请求失败。"""


class DelegationRetrievalError(DelegationError):
    """未检索到可用的公开来源。"""


class DelegationVerificationError(DelegationError):
    """回答引用未能通过公开来源核验。"""
