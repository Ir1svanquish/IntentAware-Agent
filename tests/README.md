语言：**简体中文** | [English](README.en.md)

# 测试

安装开发依赖后，从仓库根目录运行：

```bash
python -m pytest
```

测试使用临时数据库、可控制的前台观察和系统接口，不访问真实模型或互联网。原生适配器的自动化测试不能代替 Windows / Linux X11 真机检查。

| 文件 | 主要检查 |
| --- | --- |
| `test_observer.py` | Windows 原生句柄、X11 标题解析、隐私过滤、超时与平台不可用 |
| `test_task_inference.py` | 中英文标题推断、低信息标题、任务相关性与本地四分类 |
| `test_monitor.py` | 稳定采样、自动建立任务、人工修正、任务切换、暂停、排除与重启设置 |
| `test_automatic_ui.py` | 自动显示、修正草稿保留、任务建议、暂停、排除与关闭 |
| `test_classifier.py` | 原有演示分类器的四种类别、规则优先级与上下文 |
| `test_llm_client.py` | OpenAI 兼容请求、重试与超时、错误分类、密钥不泄漏 |
| `test_nlp_classifier.py` | LLM 四分类映射、Prompt 内容、非法字段、回退 |
| `test_goal_clarifier.py` | 一句话目标澄清、低置信度、CLI 与会话事件留痕 |
| `test_prompt_contract.py` | Prompt 占位符、示例 JSON 与版本哈希 |
| `test_nlp_samples.py` | 40 条开发样本、四类平衡与批量评估 |
| `test_storage.py` | 保存、更新、删除、重启与事件导出 |
| `test_session.py` | 异步分析与委托、G/P/I/D 限制、条件切换、交付与异常 |
| `test_ui.py` | Qt 操作、后台响应、结果展示与窗口布局 |
| `test_check_events.py` | 事件 JSONL 的字段与时间戳校验、委托生命周期配对、条件一致性 |

Linux 无显示环境可运行：

```bash
QT_QPA_PLATFORM=offscreen python -m pytest
```

手动验证时，分别检查普通启动、`--demo` 和 `--manual`。自动模式应在稳定窗口后显示任务或明确的不确定状态；修正主任务后切换应用，不应替换主任务或生成已确认进度。暂停和排除后不应重新出现延迟返回的活动。

[启动与开发指南](../docs/GETTING_STARTED.md)
