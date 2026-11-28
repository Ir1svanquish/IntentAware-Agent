语言：**简体中文** | [English](CONTRIBUTING.en.md)

# 组员协作指南（四周桌面版）

- **认领：** 到 [GitHub Issues](https://github.com/Ir1svanquish/IntentAware-Agent/issues) 评论认领整个模块或子任务，维护者确认 Assignee；无人默认被指派。F 为全组共享契约任务，可兼任。
- **先约定接口：** 全项目以 Python 为主，先确认数据模型、模块函数签名、SQLite schema、LLM Adapter 和实验事件格式；其他模块可用 Mock 实现并行。
- **分支：** 从 `main` 建 `feature/desktop-ui`、`feature/intent-nlp`、`feature/task-memory`、`feature/delegation`、`feature/evaluation` 或 `feature/shared-contracts`。
- **PR：** 写明改动、运行/测试步骤、错误处理和涉及的接口变更；由至少一位其他组员审阅后合并。
- **范围变动：** 从浏览器扩展转到手动输入桌面端需要导师确认；研究对照、指标与招募要求不得擅自降低。
- **隐私与诚信：** 不提交密钥、可识别参与者信息、未经批准的内容；不伪造实验结果。

## PR 验收清单

- [ ] 说明了功能和受影响的模块
- [ ] 有可复现运行步骤、正常/异常测试
- [ ] 与共享数据契约一致或已提前协调更改
- [ ] 未包含密钥或私人数据
- [ ] 涉及 G/P/I/D 时保持实验控制变量
- [ ] 至少一名其他组员完成 Review

[板块认领与详细验收](docs/WORKSTREAMS.md)
