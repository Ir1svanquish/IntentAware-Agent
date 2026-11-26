# B 目标与活动分类

本模块有两种可互换的实现，都返回 [`contracts/models.py`](../contracts/models.py) 中的共享结构：

| 实现 | 入口 | 是否需要网络 |
| --- | --- | --- |
| 本地规则（默认） | `LocalTaskRecognizer` / `LocalActivityClassifier` | 否 |
| LLM（显式开启） | `LlmActivityClassifier` / `LlmGoalClarifier` | 是，发往配置的 OpenAI 兼容端点 |
| 关键词演示（历史） | `DemoClassifier` | 否 |

## 本地规则

- `LocalTaskRecognizer.infer(ActivitySnapshot) -> TaskSuggestion`：利用应用名称和窗口标题生成候选任务、下一步、活动描述、置信度和理由；标题信息不足时返回低置信度。
- `LocalActivityClassifier.classify(ActivityContext) -> Classification`：结合任务、已确认进度与活动描述，返回直接进展、必要准备、可选探索或不确定。

规则覆盖 VS Code 系编辑器、Word/WPS 文档、PDF 阅读器与常见浏览器；未覆盖的应用或通用标题保留“不确定”。规则不读取正文，也不把窗口标题当作已完成进度。

## LLM 分类与目标澄清

- `LlmActivityClassifier`：把主任务、下一步、已确认进度、活动来源与当前活动填入 [`prompts/classify_v1.md`](prompts/classify_v1.md)，要求模型只输出 JSON，再映射为 `Classification`。
- `LlmGoalClarifier.clarify(text) -> GoalClarification`：把一句话目标提炼为 `title` / `next_step` / `confidence` / `rationale`；置信度为 `low` 时 `needs_confirmation` 为真，界面应要求补充信息而不是直接采用。
- Prompt 版本是文件内容的短哈希，例如 `classify_v1@ab12cd34`；模型名与 Prompt 版本会写进 `session_started` 与 `activity_classified` 事件，供实验复现。
- 每次成功调用还会记录 `usage`（prompt/completion/total tokens）与 `latency_ms`；`evaluate` 会汇总这两项，便于报告延迟与 token 成本。

两者都实现 [`Classifier`](../contracts/interfaces.py)，通过 `DesktopSession(classifier=...)` 注入；命令行用 `--classifier local|llm` 选择，默认 `local`。

## 配置

| 环境变量 | 默认值 | 说明 |
| --- | --- | --- |
| `INTENTAWARE_LLM_BASE_URL` | `https://api.deepseek.com/v1` | 任意 OpenAI 兼容端点，例如本地 Ollama |
| `INTENTAWARE_LLM_API_KEY` | 空 | 使用默认服务商时必填；本地端点可省略 |
| `INTENTAWARE_LLM_MODEL` | `deepseek-chat` | 实验时固定并记录 |
| `INTENTAWARE_LLM_TIMEOUT` | `20` | 单次请求秒数 |
| `INTENTAWARE_LLM_RETRIES` | `1` | 仅对 429、5xx 与超时重试 |

```bash
# 桌面应用，使用 LLM 分类（启动时会提示将发送的字段与端点）
INTENTAWARE_LLM_API_KEY=... python -m intentaware --classifier llm

# 只做目标澄清
python -m intentaware.nlp.clarify "下周三前交论文初稿，先补实验部分"
python -m intentaware.nlp.clarify --json "把论文弄一下"   # 低置信度会给出缺口

# 批量跑开发样本
python -m intentaware.nlp.evaluate tests/fixtures/nlp_samples.jsonl
```

`NlpError` 的子类区分失败原因：`NlpConfigError`（配置缺失，命令行退出码 2）、`NlpTimeoutError`、`NlpTransportError`（网络、鉴权、限流）、`NlpResponseError`（非 JSON 或字段不合约定）。异常消息不会包含 API Key。

需要界面不中断时，可传入本地回退：

```python
classifier = LlmActivityClassifier(client, fallback=LocalActivityClassifier())
```

回退结果的 `reason` 以“回退本地规则：”开头，评测时可以按前缀过滤，避免把回退样本算作模型输出。

## 隐私

LLM 模式只发送 Prompt 中的五个字段（主任务、下一步、已确认进度、活动来源、当前活动），不发送 `run_id`、`goal.id`、数据库路径或历史事件；Activity 文本可能包含窗口标题，因此必须显式开启，启动时弹窗说明目标端点。未启用时行为与之前完全一致。

## 样本与错误分析

[`tests/fixtures/nlp_samples.jsonl`](../../../tests/fixtures/nlp_samples.jsonl) 有 40 条开发样本，四类各 10 条，覆盖三类难点：

1. **同活动不同目标**：`阅读第三章` 在“写读书报告 / 下一步=阅读第三章”下是直接进展，在“提交期刊文章 / 下一步=写研究问题”下是必要准备（`dev-005` / `dev-012`）。
2. **信息不足**：`打开了一个窗口`、`未命名-1`、`新标签页` 必须判“不确定”。
3. **边界诱惑**：`刷短视频找撰写论文的灵感` 含主题词，但仍是可选探索。

这 40 条只用于回归与错误分析；E 模块另有 60 条保留评估样本，**不得**用于调 Prompt。

### 真实模型基线（2026-11-24）

配置：`deepseek-chat`、`temperature=0`、Prompt `classify_v1@0d676046`、开发集 40 条，单次运行：

```bash
INTENTAWARE_LLM_API_KEY=... python -m intentaware.nlp.evaluate tests/fixtures/nlp_samples.jsonl
```

| 指标 | 值 |
| --- | --- |
| 准确率 | 0.900（36/40） |
| Macro-F1 | 0.896 |
| 平均延迟 | 1098 ms |
| Token | 16880（prompt 14743 / completion 2137；prompt 中缓存命中 5120） |

| 类别 | support | precision | recall | F1 |
| --- | --- | --- | --- | --- |
| direct_progress | 10 | 0.900 | 0.900 | 0.900 |
| necessary_preparation | 10 | 0.909 | 1.000 | 0.952 |
| optional_exploration | 10 | 0.833 | 1.000 | 0.909 |
| unclear | 10 | 1.000 | 0.700 | 0.824 |

| 错误样本 | 期望 | 实际 | 分析 |
| --- | --- | --- | --- |
| `dev-005` | direct_progress | necessary_preparation | 目标“写读书报告”、下一步就是“阅读第三章”，模型仍按“读=准备”处理；它更依赖活动类型，没有利用 next_step 一致这一信号 |
| `dev-037` | unclear | optional_exploration | “打开了设置页面”被判成有用支线；`unclear` 门槛偏低 |
| `dev-038` | unclear | optional_exploration | “浏览网页”同类问题 |
| `dev-039` | unclear | direct_progress | “在文档里写了一些内容”被判为产出，但没有核对与目标的关系 |

主要短板是 `unclear` 召回 0.700，其余三类 F1 ≥ 0.90；误判集中在模型倾向给“有用的支线”标签而不愿承认信息不足。调整方向：把 `unclear` 的判定顺序提前，并增加“活动没有具体对象或产出时不得给出类别”的约束；调完必须在 E 的 60 条保留样本上复核，不能只优化这 40 条。

出现错误时按以下类型归类，并在 PR 中附上对应样本编号：

| 错误类型 | 表现 | 处理方向 |
| --- | --- | --- |
| 目标过宽 | 目标只有“写论文”，任何窗口都像相关 | 在 Prompt 与界面强化“先澄清目标” |
| 线索不足 | 活动描述过泛却给出确定标签 | 要求返回 `unclear`，检查样例覆盖 |
| 标签边界 | “读文献”被判直接进展 | 明确“产出成果”与“为产出做准备”的区分 |
| 过度推断 | 把窗口标题写成“已完成” | 强化 Prompt 中的不可推断约束 |
| 标题歧义 | 同一标题在不同项目下含义不同 | 依赖主任务与进度上下文，不单看标题 |

## 测试

| 文件 | 检查 |
| --- | --- |
| `test_llm_client.py` | 请求体、鉴权头、429/5xx/超时重试、错误分类、密钥不泄漏 |
| `test_nlp_classifier.py` | 四类映射、Prompt 内容、非法字段、截断、回退 |
| `test_goal_clarifier.py` | 澄清映射、低置信度、CLI 输出、会话事件留痕 |
| `test_prompt_contract.py` | 占位符齐全、示例 JSON 可解析、版本哈希稳定 |
| `test_nlp_samples.py` | 40 条样本结构、四类平衡、同活动不同目标、批量评估 |

其余：`test_task_inference.py`（标题推断）、`test_classifier.py`（旧演示规则）、`test_monitor.py`（任务状态与延迟结果）。

[接入说明](../../../docs/GETTING_STARTED.md#接入分类器或委托执行器) · [认领与验收](https://github.com/Ir1svanquish/IntentAware-Agent/issues/2)
