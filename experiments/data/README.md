# 评估样本候选池（非金标准）

本目录由 `python -m experiments.data.prepare_samples` 生成，包含：

| 文件 | 内容 | 状态 |
| --- | --- | --- |
| `holdout_contexts.jsonl` | 60 条活动上下文候选，四类各 15 条 | **候选，待评审** |
| `holdout_delegations.jsonl` | 40 条独立委托请求候选 | **候选，待评审** |
| `annotation_sheet.csv` | 两名评审的空白标注表 | 待填写 |
| `delegation_eval_sheet.csv` | 委托答案质量的空白评估表 | 待填写 |

## 学术诚信边界（务必先读）

- `expected_label` 是脚本的**场景设计意图**，不是人工标注的真值；
- `baseline_prediction` 是关键词基线的实际预测，两者有分歧的 10 条已在生成时列出；
- 全部 60 条 `review_status` 都是 `pending`，**不能**直接用于正式评估，也不能据此声称任何模型分数；
- 这些样本由程序生成，未来自真实用户，不能当作"用户研究数据"；组内实验数据必须另行按伦理流程采集。

## 转为正式保留集的步骤

1. 两名评审各自在 `annotation_sheet.csv` 独立填写 `reviewer_a_label` / `reviewer_b_label`，填写时不要看 `expected_label` 和 `baseline_prediction`，避免锚定偏差。
2. 对分歧样本讨论出 `final_label`，记录 `disagreement_reason`。
3. 把最终标签写回 JSONL（覆盖 `expected_label`），并把 `review_status` 改为 `approved`。
4. 用 `python -m experiments.evaluate isolate <B模块开发样本> holdout_contexts.jsonl` 校验与 B 模块 40 条开发样本的字面隔离。
5. 冻结样本文件（提交 PR 后不再改动），之后再跑评估。

## 与 B 模块的分工

B 模块（PR #13）的 40 条样本是**开发集**，用于调 Prompt；本目录的 60 条是**保留集**，只用于最终评估，两者必须隔离。B 模块已声明未用保留样本调 Prompt，这一约束要继续保持。
