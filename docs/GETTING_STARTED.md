# 桌面应用上手指南

需要 Python 3.11 或更新版本。先按[快速开始](../README.md#快速开始)安装项目，在仓库根目录用虚拟环境中的 Python 运行以下命令。当前任务识别和分类使用本地规则，委托使用离线示例；运行时无需联网或 API 密钥。

## 自动识别的日常使用

1. 运行 `python -m intentaware`，打开中文工作台。Windows 使用系统原生前台窗口接口；Linux X11 需要 `xprop`。macOS、Wayland 或无法读取窗口的环境会显示不可用原因，可继续使用手动输入。
2. 切到 VS Code、Word 或带有具体页面标题的浏览器，停留几秒，再回到工作台。没有已保存任务且观察信息足够时，「当前主任务」会自动生成；已有任务则继续保留。工作台同时显示当前活动、识别来源和分类理由。
3. 如任务或下一步不正确，点击 **修正**，编辑后点击 **保存修正**。已确认进度仅填写自己确实完成的内容；应用不会从窗口切换推断已完成工作。标题信息不足时，也通过这个入口补充任务。
4. 继续在其他窗口工作，当前活动会自动更新。新任务建议会显示建议的下一步，只有点击 **切换到此任务** 才会更换主任务。点 **暂不切换** 后，本次启动期间处理同一主任务时会隐藏这条建议，其他建议仍可出现。信息不足或带有休闲、购物线索的浏览器标题只用于观察活动。
5. 需要停止观察时点击 **暂停识别**，之后可点击 **恢复识别**。在「设置」中可 **排除当前应用**，或在排除列表中每行填写一个应用名称后 **保存排除列表**。暂停状态与排除设置会保留到下次启动。

「修正」会更新同一个任务并保留其支线。修正自动识别或采用过的任务后，原识别结果不会再被提示为新任务。采用新任务建议会建立新任务；旧支线仍归属于旧任务，当前页面只显示当前任务的支线。切换前需等待活动分析结束，并先查看或取消尚未结束的委托。

在 P、I 或 D 条件下，点击自动活动旁的 **暂存此活动**，会把它保存到「支线与恢复」；手动输入框中的 **暂存为支线** 保存的是补充的文字。

工作台只利用应用名称和标题，无法知道页面或文档的完整含义。打开自身窗口、标题为空、隐私窗口或被排除应用时，可能没有可用观察；这不会清除已保存任务。

### 手动模式与平台限制

用 `python -m intentaware --manual` 以识别暂停状态启动；需要时可从界面开启。点击 **修正** 保存任务，在 **手动补充活动** 中描述活动，再点击 **分析这段活动**。这是 macOS、Wayland 和其他无法采集前台窗口的环境的可用流程。

## 跑通模拟观察与离线委托

使用独立目录演示，避免改变日常任务：

```bash
python -m intentaware --demo --data-dir ./demo-data
```

窗口会明确标注模拟观察并立即启用；演示不读取真实前台窗口。不提供 `--data-dir` 时，`--demo` 默认使用常规数据目录下独立的 `demo` 子目录。

1. 在「工作台」等待模拟活动出现，检查来源和判断理由。首次使用该数据目录时会生成任务；已有任务继续保留。点击 **修正** 可查看、调整任务和下一步；需要记录进度时，填写已确认进度并 **保存修正**。
2. 展开 **手动补充活动**，输入“顺便刷短视频”，点击 **分析这段活动**。界面应显示「可能是一条支线」、判断理由和建议下一步，对应可选探索类别。四分类分别为直接进展、必要准备、可选探索和不确定。
3. 点击 **暂存为支线**，在「支线与恢复」页确认记录出现，再点击 **恢复主任务**，检查已确认进度与下一步。以同一数据目录重启后，任务、进度和支线仍应保留；在当前轮次再次点击恢复，可获得该轮次的恢复事件。
4. 保持实验条件为 **D**，打开「委托」页，输入问题并点击 **提交委托**。任务从「处理中」变为「待交付」，此时答案仍隐藏，窗口可以继续操作。
5. 点击 **到达检查点**，检查任务变为「已交付」并显示离线示例。再提交两次，分别验证 **提前查看** 与 **取消委托**：提前查看用于「待交付」任务，取消用于「处理中」或「待交付」任务。取消后应显示「已取消」，不展示该任务答案。
6. 打开「实验与记录」，点击 **导出 JSONL** 并选择文件名。检查同一 `job_id` 的 `delegation_completed` 与 `delegation_delivered` 分开记录。从仓库根目录运行 `python -m experiments.evaluate check events.jsonl` 校验导出的日志。点击 **恢复主任务** 会记录 `resume_requested`，研究计时需要另行记录提示和下一次有效主任务编辑。

「实验与记录」中的 **填入演示示例** 仅用于填入可编辑示例；检查内容后再保存修正或提交分析。

### 对照条件

| 条件 | 可验证的行为 |
| --- | --- |
| G | 可以保存或修正目标，并分析活动。 |
| P | 在 G 的基础上，可暂存支线并恢复任务。 |
| I | 在 P 的基础上，可提交异步委托，结果就绪即交付。 |
| D | 在 P 的基础上，可提交异步委托。结果就绪后，在检查点交付，也可提前查看。 |

默认条件为 D。可用 `--condition G` 等参数指定启动条件，也可在「实验与记录」中切换。自动识别不改变这些功能限制。

切换条件会开启新的实验轮次（`run_id`）并清空委托列表，旧轮次事件仍保留在 SQLite。界面只导出当前轮次，应在切换前完成导出。切换前须等待分析结束，并交付或取消所有「处理中」或「待交付」的委托。委托只在当前轮次中可操作，重启后可继续使用本地任务、进度与支线。

## 开发从哪个文件开始

| 板块 | 改动入口 | 验证方式 |
| --- | --- | --- |
| [A 桌面交互](https://github.com/Ir1svanquish/IntentAware-Agent/issues/1) | [`ui/window.py`](../src/intentaware/ui/window.py) 的 `MainWindow`，以及 [`ui/theme.py`](../src/intentaware/ui/theme.py)。工作台、修正、状态反馈与侧栏页面。 | [`test_ui.py`](../tests/test_ui.py)、[`test_automatic_ui.py`](../tests/test_automatic_ui.py) 和上述操作。 |
| [B 目标与活动分类](https://github.com/Ir1svanquish/IntentAware-Agent/issues/2) | [`nlp/local.py`](../src/intentaware/nlp/local.py) 的 `LocalTaskRecognizer` 与 `LocalActivityClassifier`。[`nlp/demo.py`](../src/intentaware/nlp/demo.py) 保留原有离线分类器。 | [`test_task_inference.py`](../tests/test_task_inference.py)、[`test_classifier.py`](../tests/test_classifier.py)，覆盖标题推断、低置信度和四分类。 |
| [C 任务记忆与恢复](https://github.com/Ir1svanquish/IntentAware-Agent/issues/3) | [`memory/store.py`](../src/intentaware/memory/store.py) 的 `SQLiteStore`；[`DesktopSession.resume()`](../src/intentaware/session.py) 组织恢复提示。 | [`test_storage.py`](../tests/test_storage.py) 和同一数据目录重启检查。 |
| [D 异步委托](https://github.com/Ir1svanquish/IntentAware-Agent/issues/4) | [`delegation/demo.py`](../src/intentaware/delegation/demo.py) 的 `DemoDelegator`；[`session.py`](../src/intentaware/session.py) 管理后台执行与交付。 | [`test_session.py`](../tests/test_session.py)，检查完成、交付、失败与取消。 |
| [E 研究评估](https://github.com/Ir1svanquish/IntentAware-Agent/issues/5) | [实验评估工具](../experiments/README.md)和[候选样本](../experiments/data/README.md)。 | 分别导出 G/P/I/D JSONL，用 `experiments.evaluate` 核对事件。正式恢复计时还需接入同一任务的提示与有效编辑事件。 |
| [F 前台观察与集成](https://github.com/Ir1svanquish/IntentAware-Agent/issues/6) | [`activity/observer.py`](../src/intentaware/activity/observer.py) 适配系统；[`activity/monitor.py`](../src/intentaware/activity/monitor.py) 稳定采样与协调任务；[`__main__.py`](../src/intentaware/__main__.py) 装配模式。 | [`test_observer.py`](../tests/test_observer.py)、[`test_monitor.py`](../tests/test_monitor.py) 和完整测试。 |

共享任务类型与接口位于 [`contracts/models.py`](../src/intentaware/contracts/models.py) 和 [`contracts/interfaces.py`](../src/intentaware/contracts/interfaces.py)，窗口观察与候选任务类型位于 [`activity/models.py`](../src/intentaware/activity/models.py)。默认数据目录由 [`config.py`](../src/intentaware/config.py) 选择。

## 接入分类器或委托执行器

在 `nlp/` 或 `delegation/` 新建实现类，按 [`contracts/interfaces.py`](../src/intentaware/contracts/interfaces.py) 实现对应方法。开发时用构造函数注入；若要让命令行入口使用新实现，在 [`__main__.py`](../src/intentaware/__main__.py) 创建 `DesktopSession` 的位置传入实例。

```python
session = DesktopSession(
    store,
    classifier=my_classifier,
    delegator=my_delegator,
    condition=Condition.D,
)
```

这里的 `store` 是 `SQLiteStore` 实例，`my_classifier` 与 `my_delegator` 是新实现实例。只替换其中一个时，可省略另一个参数以继续使用会话的默认实现。

- `Classifier.classify(context: ActivityContext) -> Classification` 从目标、活动与用户确认的进度取得输入，返回 `ActivityLabel`、理由与建议下一步。外部请求需有有限超时。`session.start_analysis(activity)` 在后台提交分类；`session.analyze(activity)` 是同步入口。带有监视器的界面通过 `monitor.analyze_manual(activity)` 提交人工补充，保留结果直到任务或观察上下文变化。
- `Delegator.run(question: str, cancel: threading.Event) -> DelegationResult` 返回非空答案与最多两条 `Source(title, url)`。请求需有有限超时，在操作前后检查 `cancel.is_set()`；需要等待时可用能提前结束的 `cancel.wait(seconds)`。
- 后台实现只处理输入并返回结果，或抛出异常交给会话处理。主线程通过 `session.poll()` 接收结果。Qt 控件与 SQLite 连接留在主线程。

自动观察由 `TaskMonitor` 调用观察器的 `capture() -> CaptureResult`，稳定后使用 `LocalTaskRecognizer.infer(snapshot)` 生成候选任务，再协调后台活动分类。替换观察器时保留空闲、排除与不可用状态，给外部命令设置超时；暂停、排除或关闭后不得应用之前发出的延迟结果。

当前推断是本地规则，委托是离线示例。接入真实模型或检索前，同步更新界面模式提示与事件模式标记，并为评估记录模型、提示词和观察模式。不要把标题分类结果写成用户已完成的进度。

扩展存储时，用 `with store.transaction():` 将一次操作的数据修改与事件记录共同提交。保存失败应整体回滚，界面状态只在提交成功后更新。

## 本地数据与测试

SQLite 文件名为 `intentaware.sqlite3`，默认目录如下。

| 系统 | 数据目录 |
| --- | --- |
| Windows | `%LOCALAPPDATA%\IntentAware` |
| macOS | `~/Library/Application Support/IntentAware` |
| Linux | `$XDG_DATA_HOME/IntentAware`，未设置时为 `~/.local/share/IntentAware` |

用 `--data-dir ./demo-data` 指定独立目录，也可设置 `INTENTAWARE_DATA_DIR`。命令行参数优先；应用不会自动加载 `.env`。同一目录中的任务、已确认进度、支线、暂停状态与排除应用会保留。

自动观察不采集截图、键盘输入或剪贴板，不读取正文，也不上传窗口数据。持续观察到的原始标题不追加到事件导出；由标题生成或用户修正的任务会保存，可能含文件或页面名称。用户主动保存的支线与进度也属于本地记录，分享前检查内容。

安装开发依赖后，从仓库根目录运行：

```bash
python -m pytest
```

Linux 无显示环境可运行：

```bash
QT_QPA_PLATFORM=offscreen python -m pytest
```

测试使用临时数据库和可控制的观察输入。原生适配器仍需在 Windows 或 Linux X11 真机验证；无显示测试不能证明系统已授予窗口访问权限。提交 PR 时附相关测试结果，以及可复现的正常、失败或取消操作。

[项目首页](../README.md) · [认领任务](WORKSTREAMS.md)
