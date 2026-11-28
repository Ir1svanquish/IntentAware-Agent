语言：**简体中文** | [English](README.en.md)

# IntentAware-Agent

**HKU COMP7607 · Natural Language Processing · Group 14**

根据前台应用和窗口标题，自动整理当前任务与活动；需要时点击「修正」，继续自己的工作。识别使用本地规则，当前版本不读取页面或文档正文。

## 快速开始

在 **设置 → 界面语言** 中选择简体中文或英文，重启后界面和反馈会一起切换。也可以用 `python -m intentaware --lang en` 临时用英文启动。

需要 Python 3.11 或更新版本。在仓库根目录运行以下命令。

**Windows（PowerShell）**

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m intentaware
```

安装 Python 后，也可双击 [start.bat](start.bat) 以自动识别模式启动。首次安装依赖需联网，之后可离线运行。

[MVP 演示与一分钟讲稿](docs/MVP_DEMO.md)

**macOS / Linux**

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m intentaware
```

启动后，切到 VS Code、Word 或带有具体页面标题的浏览器窗口，停留几秒，再回到工作台。没有已保存任务且标题信息足够时，应用会自动填入「当前主任务」；当前活动和分类也会随窗口变化更新，无需逐条输入。已有任务会保留，标题信息不足时可点击「修正」。默认实验条件为 D。

[完整操作、模块接入与测试](docs/GETTING_STARTED.md)

### 平台与启动模式

| 环境 | 自动识别 |
| --- | --- |
| Windows | 使用系统原生接口读取前台应用与窗口标题 |
| Linux X11 | 需要可用的图形会话和 `xprop` 命令 |
| macOS / Linux Wayland | 当前不支持自动识别；界面会说明原因，可手动填写任务和活动 |

| 命令 | 启动后行为 |
| --- | --- |
| `python -m intentaware` | 自动识别；上次保存的暂停状态与排除应用设置继续生效 |
| `python -m intentaware --demo` | 使用明确标注的模拟窗口观察，默认保存到独立的 `demo` 数据子目录 |
| `python -m intentaware --manual` | 以手动模式启动，自动识别暂停；可在界面重新开启 |

运行命令时使用上面的虚拟环境 Python 路径，或先激活虚拟环境。

### 当前可用

- 支持简体中文和英文的 PySide6 工作台，自动显示当前任务、正在进行的活动、识别来源和判断理由；手动输入放在「修正」和「手动补充活动」中。
- 根据稳定、信息充分的窗口生成首个任务，并用本地规则进行四分类。新的任务建议可点击「切换到此任务」采用，也可以选择「暂不切换」保留当前任务。
- 暂停、恢复和排除应用可在界面操作，相关设置保存在本地。标题信息不足时保留不确定状态，等待人工修正。
- 目标、已确认进度和偏离记录写入本地 SQLite。重新打开应用后，可以继续当前目标。
- G/P/I/D 功能开关，后台委托、立即或延迟展示、提前查看和取消，以及当前实验轮次事件的 JSONL 导出。委托任务随本次应用会话结束。
- 默认以本地规则分类，委托使用离线演示。可通过 `--classifier llm` 启用[模型分类](docs/GETTING_STARTED.md#llm-分类可选)，通过 `--delegator live` 启用[公开来源委托](src/intentaware/delegation/README.md)。

### 桌面界面

![IntentAware 桌面工作台实际运行截图](docs/images/desktop-starter.png)

## 项目简介

**IntentAware-Agent** 是面向学习、写作与编程场景的桌面任务助手。默认版本从前台应用和标题获取线索，结合主目标判断活动，并保存支线与用户确认的进度。可配置 OpenAI 兼容模型进行活动四分类，也可用 `--delegator live` 将支线问题交给后台查找公开来源，在检查点查看核对过的正文摘录。

### 项目提案

[查看课程 Proposal（PDF）](docs/group14-project-proposal.pdf)

原提案规划的是浏览器扩展。当前实现改为基于 Python 和 PySide6 的独立桌面软件，通过前台应用和窗口标题识别任务。

### 典型使用流程

1. **开始工作：** 启动应用后继续在编辑器或浏览器中工作，稳定且有足够信息的窗口标题会生成首个任务。
2. **检查与修正：** 查看识别来源；如任务或下一步有误，点击「修正」后保存。人工修正的任务会保留。
3. **查看活动：** 工作台自动更新当前活动，并显示直接进展、必要准备、可选探索或不确定的判断与理由。窗口切换不会自动确认任何进度。
4. **处理新任务与支线：** 需要换主任务时采用新任务建议；也可以暂存支线，或通过离线演示委托验证后台与交付流程。
5. **恢复任务：** 根据用户确认的进度与下一步继续工作；暂停识别、排除应用以及实验记录可从侧栏进入。

## 模块目标

下表包含后续要完成的能力；当前实现范围见上面的「当前可用」。

| 模块 | 功能 |
| --- | --- |
| **Goal & Intent** | 澄清任务目标、提取下一步行动；结合上下文进行四分类并解释判断依据 |
| **Detour & Resume** | 保存链接、笔记与已确认进度；生成具体的任务恢复建议 |
| **Async Delegation** | 将问题整理成可编辑的委托请求；后台检索最多两份公开来源并生成带引用的回答 |
| **Deferred Delivery** | 根据用户选定的检查点控制答案展示，支持提前查看和取消 |
| **Experiment & Evaluation** | 记录任务事件，切换实验条件并评估分类、任务恢复与委托效果 |

## 技术架构

| 组件 | 技术 |
| --- | --- |
| 桌面界面 | **Python + PySide6** |
| 前台观察 | Windows 原生接口 / Linux X11 `xprop` |
| NLP 推理 | 本地任务推断与活动分类规则，预留 LLM 接口 |
| 本地数据 | SQLite |
| 异步处理 | Python 后台 Worker / 线程 |
| 实验分析（计划） | pandas + scikit-learn |
| 自动化测试 | pytest |

应用采用 Python 模块化结构。前台观察在后台采样，稳定后由任务监视器交给本地识别与活动分类；用户可随时补充或修正。任务、用户确认的进度和设置保存在本地，界面在主线程接收后台结果并更新。

## 研究与实验

项目采用四种功能条件进行比较：

| 条件 | 功能 |
| --- | --- |
| **G** | 目标感知提醒 |
| **P** | G + 分心记录与任务恢复 |
| **I** | P + 异步委托，结果就绪后展示 |
| **D** | P + 异步委托，在任务检查点展示结果（支持提前查看） |

计划开展预实验及 12–18 名成年参与者的组内对照研究；另外评估 **60 个活动上下文样本**和 **40 个独立保留的委托请求**。

主要指标包括活动分类的 Macro-F1 和误提醒率、任务完成与输出质量、恢复主任务所需时间、委托答案的引用支持情况、用户感知负担、延迟和 Token 使用量。恢复时间以可记录的下一次有效主任务编辑为终点。

## 四周开发计划

| 周次 | 主要交付 |
| --- | --- |
| **第 1 周** | 项目框架、PySide6 界面、共享数据结构、SQLite 与 LLM 接口；启动实验准备 |
| **第 2 周** | Goal & Intent、Detour & Resume 的完整基础流程 |
| **第 3 周** | Async Delegation、Deferred Delivery、实验条件切换与集成测试 |
| **第 4 周** | 预实验与评估、结果分析、演示和最终报告 |

## 项目结构

```text
src/intentaware/
├── ui/             # 中文桌面工作台
├── activity/       # 前台观察、稳定采样与任务监视器
├── nlp/            # 本地任务推断与活动分类，预留 LLM 接口
├── memory/         # 任务进度、分心记录与恢复
├── delegation/     # 离线演示与公开来源委托
├── contracts/      # 共享数据结构与接口
├── session.py      # 功能开关、后台协调与交付
└── __main__.py     # 命令行入口

experiments/        # 实验任务、日志与分析
tests/              # 自动化测试
docs/               # 技术文档与分工说明
TODO.md             # 开发任务清单
CONTRIBUTING.md     # 团队协作规范
```

## 小组协作

项目开放六个任务板块，组员可以在对应 GitHub Issue 中认领整个模块或具体子任务：

**[A 桌面界面](https://github.com/Ir1svanquish/IntentAware-Agent/issues/1)** · **[B NLP](https://github.com/Ir1svanquish/IntentAware-Agent/issues/2)** · **[C 任务记忆](https://github.com/Ir1svanquish/IntentAware-Agent/issues/3)** · **[D 异步委托](https://github.com/Ir1svanquish/IntentAware-Agent/issues/4)** · **[E 研究评估](https://github.com/Ir1svanquish/IntentAware-Agent/issues/5)** · **[F 接口与集成](https://github.com/Ir1svanquish/IntentAware-Agent/issues/6)**

[查看所有待认领任务](https://github.com/Ir1svanquish/IntentAware-Agent/issues) · [详细认领与验收指南](docs/WORKSTREAMS.md) · [开发 TODO](TODO.md) · [协作规范](CONTRIBUTING.md)


### 加入开发组

组员可在 [加入申请 Issue #7](https://github.com/Ir1svanquish/IntentAware-Agent/issues/7) 留下 GitHub 用户名和想认领的模块，维护者确认后邀请加入；也可先 Fork 仓库提交 Pull Request。

## 数据与隐私

自动观察只读取前台应用名称和窗口标题。默认使用本地规则分类，观察数据留在本机。应用会跳过自身窗口和符合过滤规则的隐私窗口与密码管理器。可在「设置」中增加排除应用，也可随时暂停识别。

启用 `--classifier llm` 后，主任务、下一步、已确认进度、活动来源和当前活动会发送到配置的模型端点。当前活动可能包含前台应用名称和窗口标题。应用不采集截图、键盘输入或剪贴板，也不读取页面、文件或文档正文。

任务、用户确认的进度、支线和设置保存在本地 SQLite。自动生成或人工修正的任务标题也会保存，可能包含文件或页面名称；持续观察到的原始窗口标题不会追加到事件导出中。导出实验记录前检查是否含有用户主动保存的敏感内容。数据目录与切换方法见[上手指南](docs/GETTING_STARTED.md#本地数据与测试)。

本地标题规则只能给出有限线索，分类不代表已经完成编辑或取得进展。研究中的有效主任务编辑仍需独立观测。接入模型时，通过本地环境变量提供 API 密钥，并单独明确将要发送的数据。
