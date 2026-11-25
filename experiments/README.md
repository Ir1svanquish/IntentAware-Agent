语言 / Language：**简体中文** | [English](README.en.md)

# 研究实验

保留 Proposal 的 **G/P/I/D** 条件、**60 个活动上下文样本**（两位评审）、**40 个独立保留的委托请求**，以及计划中的 **12–18 名成年参与者组内实验**。研究尚未完成；实验准备从第 1 周开始，参与者测试须先满足同意及伦理要求。

当前桌面端可自动观察应用名称与窗口标题，使用本地规则推断任务和分类活动。`--demo` 使用模拟观察，委托仍是离线示例。实验时记录平台、观察模式、规则或模型版本，并将模拟演示数据与正式评估分开。开发样本和保留评估样本也须分离。

| 评估内容 | 计划指标或记录 |
| --- | --- |
| 活动分类 | 关键词基线、Macro-F1、误提醒率；检查低置信度与人工修正情况 |
| 任务表现 | 任务完成情况、输出质量、恢复主任务所需时间 |
| 委托结果 | 答案质量、来源与引用支持、未解决点 |
| 使用负担与成本 | 感知负担、延迟、Token 用量；本地规则和离线演示不作为真实模型结果 |

「实验与记录」导出当前 `run_id` 的 JSONL。按 `job_id` 区分 `delegation_completed`（后台就绪）与 `delegation_delivered`（交付）；点击恢复产生 `resume_requested`。恢复时间终点必须是**下一次有意义的主任务编辑**，不能用返回按钮、窗口切换或标题分类替代，需在受控研究中另行观测。

持续观察的原始窗口标题不会追加到事件导出，自动生成或人工修正的任务标题会保存在本地任务中。实验记录避免包含可识别个人数据，分享前检查用户主动保存的任务、进度与支线内容。

## E 模块评估工具

统一入口为 `python -m experiments.evaluate`，全部只用 Python 标准库，不需要 API 密钥。宏大的样本标注、两名评审核查和 12–18 人组内实验仍需研究者按伦理流程完成，工具只做可复现的机械计算，不生成或伪造数据。

```bash
# 1. 导出事件自检：结构与委托生命周期
python -m experiments.evaluate check events.jsonl

# 2. 保留样本上的关键词基线：Macro-F1、混淆矩阵、误提醒率
python -m experiments.evaluate baseline experiments/data/holdout_contexts.jsonl

# 3. 事件日志指标：委托处理/交付延迟、恢复时间
python -m experiments.evaluate events events.jsonl

# 4. 开发集与保留集的字面隔离检查
python -m experiments.evaluate isolate dev_samples.jsonl holdout_contexts.jsonl
```

每个子命令加 `--json` 可输出结构化结果。退出码：`0` 正常，`1` 检查未通过，`2` 输入错误。

### 与 B 模块的分工

B 模块 `nlp/evaluate.py` 负责用 LLM 分类器跑样本并计算 Macro-F1、逐标签 P/R/F1 和 Token/延迟；E 模块不重复实现这部分，只做：

- **关键词基线**：`baseline.py` 提供可复现的下界，接口兼容 B 模块的 `Classifier`，可注入 `nlp.evaluate`。
- **误提醒率**：`metrics.py` 在 G 条件下把"实际在推进任务、却被判为分心/不确定"当作误提醒，口径写在输出里。
- **事件指标**：`analyze_events.py` 计算委托处理延迟（提交→完成）、交付延迟（完成→交付）和恢复时间。
- **样本隔离**：`samples.py` 检查开发集与保留集的 ID、活动描述和目标+活动组合是否重复。

### 恢复时间的硬约束

恢复时间从**支线提示出现**（`distraction_prompted`）开始，到**下一次有意义的主任务编辑**（`effective_edit`）结束，两者必须在同一 `run_id`、同一 `goal_id` 下。起点**只认提示事件**：`detour_saved`（手动保存支线）不是提示，不作为起点，否则同一次分心会因"提示 + 手动保存"被算成两笔。研究者需在受控研究中显式记录起点和终点：

```python
session.record_event("distraction_prompted", {"source": "optional_exploration"})
session.record_event("effective_edit", {"source": "goal_correction"})
```

`resume_requested`（点击"恢复主任务"按钮）**只作参考计数，不作为计时起点**——用户可能在提示出现很久后才点恢复，用它计时会漏掉中间的分心时长。例如提示在第 0 秒、点击恢复在第 8 秒、编辑在第 10 秒，恢复时间是 10 秒而不是 2 秒。

跨任务的下一次编辑不算恢复；缺少起点或缺终点时分别列入 `missing_start` / `missing_end` 并报告不可计算，**绝不用按钮点击、窗口切换或标题分类替代**。这是 Proposal 的明确要求。

交付延迟（`analyze_events.py`）只统计 `completed -> delivered`；缺少 `delegation_completed` 的委托保留在 `missing_completion`，并从交付延迟中排除，不会拿提交时间冒充完成时间。

### 样本格式

分类样本沿用 B 模块格式，每行一个 JSON 对象：

```json
{"id": "holdout-001", "goal_title": "...", "goal_next_step": "...", "progress": "...", "activity": "...", "expected_label": "direct_progress"}
```

标签取 `direct_progress` / `necessary_preparation` / `optional_exploration` / `unclear`。开发样本（B 模块 40 条）与保留样本（E 模块 60 条）必须分开存放，提交前用 `isolate` 校验。测试见 [`tests/test_check_events.py`](../tests/test_check_events.py) 和 [`tests/test_experiment_evaluation.py`](../tests/test_experiment_evaluation.py)。

[上手指南](../docs/GETTING_STARTED.md) · [开发与评估任务](../TODO.md)
