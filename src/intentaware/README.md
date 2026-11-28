语言：**简体中文** | [English](README.en.md)

# PySide6 桌面应用源码

从仓库根目录安装后，用 `python -m intentaware` 打开中文工作台。常规启动观察前台应用和窗口标题，使用本地规则推断任务与分类活动；`--demo` 使用模拟观察，`--manual` 以识别暂停状态启动。委托执行器仍为离线演示。

| 入口 | 作用 |
| --- | --- |
| A [桌面交互](ui/README.md) | `ui/window.py` 与 `ui/theme.py`：当前任务、自动活动、人工修正、支线、委托与实验页面。 |
| B [目标与活动分类](nlp/README.md) | `nlp/local.py`：`LocalTaskRecognizer` 推断候选任务，`LocalActivityClassifier` 提供四分类。`nlp/demo.py` 保留原有演示分类器。 |
| C [任务记忆](memory/README.md) | `memory/store.py`：SQLite 保存任务、用户确认的进度、支线、事件和观察设置。 |
| D [异步委托](delegation/README.md) | `delegation/demo.py`：离线后台委托，用于验证完成、交付和取消流程。 |
| E [研究评估](../../experiments/) | 使用当前 G/P/I/D 轮次的 JSONL 事件，并独立观测有效主任务编辑。 |
| F [前台观察](activity/README.md)与[共享接口](contracts/README.md) | `activity/` 负责平台适配、稳定采样与任务监视器；`contracts/`、`session.py` 与 `__main__.py` 负责类型、会话与启动装配。 |

观察器在 Windows 使用原生系统接口，在 Linux X11 使用 `xprop`；macOS 和 Wayland 暂不支持自动观察。原始持续窗口标题不写入事件导出，自动生成的任务标题会作为本地任务保存。窗口观察不会自动填写已确认进度。

同一数据目录可恢复任务、进度、支线与暂停/排除设置。委托任务只在当前实验轮次中可操作，重启不恢复正在执行的委托。

[运行、扩展与测试](../../docs/GETTING_STARTED.md) · [项目首页](../../README.md) · [认领任务](../../docs/WORKSTREAMS.md)
