# D 异步委托与延迟交付

[`demo.py`](demo.py) 提供默认的离线演示。联网模式支持后台整理请求、抓取最多两份候选公开来源，并展示可在网页正文中核对的原文摘录。

## 模块结构

| 文件 | 职责 |
| --- | --- |
| [`config.py`](config.py) | 读取检索提供方、来源上限（`1..2`）、超时与摘录长度等环境变量 |
| [`errors.py`](errors.py) | `DelegationError` 异常体系（配置、超时、网络、检索为空、引用核验失败） |
| [`models.py`](models.py) | `DelegationDraft`、`SearchHit`、`RetrievedDocument`、`CitationClaim`、`VerificationReport` |
| [`prompts.py`](prompts.py) / [`prompts/`](prompts) | 版本化 Markdown Prompt（`formulate_v1`、`answer_v1`） |
| [`formulator.py`](formulator.py) | `LocalRequestFormulator` 与 `LlmRequestFormulator`：生成可编辑请求并硬限最多一次澄清 |
| [`retriever.py`](retriever.py) | `PublicWebRetriever`（免 Key DuckDuckGo + Wikipedia 兜底，或 Tavily）与 `MockRetriever` |
| [`verifier.py`](verifier.py) | `CitationVerifier`：在已抓取的网页正文中逐字核对每条摘录 |
| [`agent.py`](agent.py) | `LiveDelegator`：实现 `Delegator.run(question, cancel)`，按次隔离并发统计 |
| [`evaluate.py`](evaluate.py) | 批量运行留出委托样本并导出供双人复核的评估 CSV |

## 环境变量

大模型端点继续复用 B 模块的 `INTENTAWARE_LLM_*` 配置；检索相关环境变量如下：

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `INTENTAWARE_SEARCH_PROVIDER` | `public` | `public`（免 Key：DuckDuckGo + Wikipedia 兜底）或 `tavily` |
| `INTENTAWARE_SEARCH_API_KEY` | 空 | 使用 `tavily` 时必填 |
| `INTENTAWARE_SEARCH_BASE_URL` | 空 | 可选自定义 Tavily 端点 |
| `INTENTAWARE_DELEGATION_MAX_SOURCES` | `2` | 每次委托最多尝试抓取的候选网页数，抓取失败也计入（`1..2`） |
| `INTENTAWARE_DELEGATION_SEARCH_TIMEOUT` | `8.0` | 搜索请求超时秒数 |
| `INTENTAWARE_DELEGATION_FETCH_TIMEOUT` | `8.0` | 单页抓取超时秒数 |
| `INTENTAWARE_DELEGATION_MAX_EXCERPT_CHARS` | `2500` | 单份来源正文摘录最大字符数 |

## 运行与评测

在桌面端点「用模型整理」会把当前输入的问题发给配置的模型。补充澄清也会发给模型。确认编辑后的委托才会开始搜索，主任务标题和窗口观察不会自动随委托发送。

网页抓取直接连接经过校验的公网地址，并检查每次重定向。这个抓取流程需要直连公网。只在搜索结果里出现的摘要不能作为核验依据。答案区域展示带来源编号的已核对摘录，待核对问题单独标注为模型整理。

```bash
# 桌面端启用真实公开检索 + LLM 异步委托
INTENTAWARE_LLM_API_KEY=... python -m intentaware --delegator live

# 使用 Tavily 批量运行 40 条留出委托样本并导出评分表草稿
INTENTAWARE_LLM_API_KEY=... \
INTENTAWARE_SEARCH_PROVIDER=tavily \
INTENTAWARE_SEARCH_API_KEY=... \
python -m intentaware.delegation.evaluate experiments/data/holdout_delegations.jsonl --out-csv delegation_eval.csv
```

[`session.py`](../session.py) 管理任务状态与 I/D 交付时机：I 条件完成即交付，D 条件进入 `READY` 等待检查点或提前查看，并在事件中记录 `sources_count`、模型、Prompt 版本、耗时与 Token 用量。

[接入说明](../../../docs/GETTING_STARTED.md#接入分类器或委托执行器) · [认领与验收](https://github.com/Ir1svanquish/IntentAware-Agent/issues/4)
