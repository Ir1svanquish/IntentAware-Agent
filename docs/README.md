语言：**简体中文** | [English](README.en.md)

# 项目文档

- [桌面应用上手指南](GETTING_STARTED.md)：安装、自动识别、手动修正、离线演示、模块接入和测试。
- [MVP 演示与一分钟讲稿](MVP_DEMO.md)。
- [任务认领与验收](WORKSTREAMS.md)：各板块的任务与交付要求。
- [共享数据](../src/intentaware/contracts/models.py)与[模块接口](../src/intentaware/contracts/interfaces.py)：跨模块输入输出约定。
- [前台观察与任务监视器](../src/intentaware/activity/)：平台适配、稳定采样、暂停与排除应用。
- [本地识别](../src/intentaware/nlp/local.py)：从标题推断任务并分类活动。
- [流程协调](../src/intentaware/session.py)：后台执行、状态更新和事件记录。
- [测试说明](../tests/README.md)：自动化验证入口。
