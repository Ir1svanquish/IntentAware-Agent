[English](MVP_DEMO.en.md)

# IntentAware-Agent MVP 演示

## 运行演示

在仓库根目录的虚拟环境中安装应用，并为这次演示使用一个新的数据目录。演示使用模拟前台窗口、本地活动分类和一段预置的文档摘录。安装后可离线运行。

```bash
python -m pip install .
python -m intentaware --lang zh --demo --condition D --data-dir ./demo-mvp
```

在 Windows 上也可以运行 `.\start.bat --lang zh --demo --condition D --data-dir demo-mvp`。脚本会准备虚拟环境并启动同一个演示。

1. 等待工作台根据模拟编辑器窗口识别出 IntentAware-Agent 的开发任务。
2. 打开 **实验与记录 → 填入演示示例**。点击 **保存修正**，保存主任务、下一步和已确认进度。点击 **分析这段活动**，工作台提示可能是一条支线后，点击 **暂存为支线**。
3. 打开 **委托 → 整理请求**，确认并提交预填的 `argparse` 问题。等到状态显示 **待交付** 后，打开 **支线与恢复 → 恢复主任务**，查看已确认的进度和下一步。这时答案仍未显示。
4. 回到 **委托**，点击 **到达检查点**，查看核对过的原文摘录和来源。用另一份数据目录以 `--condition I` 运行，可以用相同的问题和证据对比即时交付。
5. 正式实验中，观察员看到参与者对主任务做了有意义的修改后，在 **实验与记录** 中点击 **记录有效主任务编辑**。工作台会另行记录支线提示的出现时间。点击 **导出 JSONL**，将文件保存为 `events-demo.jsonl`。导出记录会标明本次运行是演示。

```bash
python -m experiments.evaluate check events-demo.jsonl
python -m experiments.evaluate events events-demo.jsonl
python -m experiments.evaluate baseline tests/fixtures/nlp_samples.jsonl
```

## 一分钟讲稿

**项目动机。** 做主任务时，临时冒出来的问题容易打断思路。IntentAware 让用户先记下这些支线，回来时能看到做到哪一步、接下来该做什么。

**研究方法。** 我们按活动与主任务的关系做四分类，并设计了四种实验条件，分别提供目标提醒、支线暂存与恢复、即时委托交付和检查点交付。后两种条件使用同一套委托流程，可以对比交付时机。

**实现。** 我们用 PySide6 做了桌面工作台，从前台应用名和窗口标题获得线索，让用户修正任务，用 SQLite 保存进度，并在后台处理委托。演示用预置来源展示如何核对摘录，并在用户到达检查点后显示结果。

**主要结果。** 在 40 条开发样本上，关键词基线准确率为 87.5%，宏平均 F1 为 0.876。一次 DeepSeek 运行的准确率为 90.0%，宏平均 F1 为 0.896。桌面演示也跑通了任务恢复、延迟交付和事件导出。保留集评估和参与者实验仍待完成。

## 验证记录与演示范围

- [分类结果、运行配置与错误分析](../src/intentaware/nlp/README.md#真实模型基线2026-11-24)。两组数字使用同一批 40 条开发样本。DeepSeek 数字来自已记录的运行。关键词基线可用上面的命令复现。
- [桌面集成测试](../tests/test_automatic_ui.py)覆盖自动识别、手动修正、暂存支线、重启后恢复任务、延迟交付，以及在 JSONL 导出中配对支线提示与有效编辑。
- 当前实现是读取前台应用名和窗口标题的桌面应用。[项目提案](group14-project-proposal.pdf)里描述的是浏览器方案。Windows 前台采集、真实检索和模型调用可以在离线演示之外单独验证。参见[联网委托设置](../src/intentaware/delegation/README.md)和[实验指南](../experiments/README.md)。
