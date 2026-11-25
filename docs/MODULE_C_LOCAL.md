# C 模块：任务记忆与恢复

基于上游 `5f9e1175f6a929283b375e866fbb2648aba4a863`，提交分支为 `feature/task-memory`。

## 功能与接口

- 支线笔记、HTTP(S) 链接和用途的新增、查看、编辑与删除。
- SQLite 保存目标、用户确认的进度及支线，重启后恢复；支线保持原任务归属。
- 基于已保存目标、进度和下一步生成恢复提示，不调用 API，不推断用户已完成的工作。
- 支持忽略当前版本的提示、暂停／开启提示；设置跨重启保留，暂停时仍可手动恢复。
- 修改目标或进度后更新恢复提示；保存失败时保留编辑草稿。
- 数据变更与对应事件在同一事务提交，失败整体回滚。

共享数据结构 `Detour` 在原有字段后增加 `url`、`purpose`，默认均为空字符串，兼容原有构造调用。旧数据库打开时自动追加字段，不删除旧记录。

新增／扩展接口：

```python
session.add_detour(text, url="", purpose="")
session.update_detour(detour_id, text, url="", purpose="")
session.remove_detour(detour_id)
session.recovery_preview()
session.ignore_recovery()
session.set_recovery_paused(paused)
session.resume()
```

新增事件为 `detour_updated`、`recovery_ignored`、`recovery_paused`、`recovery_resumed`。事件记录标识与状态，不附支线正文；`resume_requested` 仍不代表有效主任务编辑。

## 安装与运行

依赖及 Python 版本与项目 README 一致。创建标准虚拟环境后运行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
zsh ./test-memory.command
zsh ./start-memory.command
```

两个 `.command` 脚本用于 macOS 本地测试；显式使用脚本对应的 `zsh` 运行，无需依赖网页上传是否保留可执行权限。启动脚本采用手动模式、P 条件和独立的 `local-memory-data/` 数据目录。也可直接使用跨平台命令：

```bash
python -m pytest -q
python -m intentaware --manual --condition P --data-dir ./local-memory-data
```

## 验证结果（2026-11-24）

迁移到具有真实上游 Git 历史的提交分支后，使用已有 Python 3.12 / PySide6-Essentials 6.8.3 环境运行完整测试，结果为 **147 passed in 10.29s**。此前开发目录完整测试同为 147 项通过。

测试覆盖：

- 旧数据库升级、升级后编辑、关闭后重新读取。
- 任务、进度、支线、链接和用途的完整持久化流程及跨任务隔离。
- 多个独立解释器退出／启动后的数据和提示设置恢复。
- 空记录、无效链接、数据库真实写锁，以及解锁后重试。
- 事件写入受约束时的目标、进度及恢复设置整体回滚。
- UI 正常及错误输入、保存失败保留草稿、任务切换关闭旧编辑器。
- G/P/I/D 后端门控与原有界面回归。

实际桌面已确认：目标和进度保存；支线新增／编辑／删除；空输入和无效链接错误反馈；提示更新／忽略／暂停／手动恢复；用户重新启动应用后目标、进度及支线内容恢复。SQLite 独立只读连接的完整性检查为 `ok`。

### Windows CI 编码修复（2026-11-24）

首次 Windows CI 为 145 项通过、2 项跨进程测试失败。本地在 `cp1252` 标准输出环境中复现：子进程打印包含中文的 JSON 时发生 `UnicodeEncodeError`。测试助手现为子进程设置 `PYTHONIOENCODING=utf-8`，并在父进程显式使用 UTF-8 解码；失败时输出退出码和完整 stdout/stderr，便于定位问题。

跨进程测试现在覆盖 UTF-8／cp1252 环境及暂停／未暂停两种状态的组合，修复后本地 **4 passed in 1.89s**。验证命令为 `.venv/bin/python -m pytest -q tests/test_memory_process.py`。应用代码与原有断言保持不变，Windows 全量结果以 PR 的最新 CI 记录为准。

### 旧数据库并发迁移修复（2026-11-24）

按 PR #14 的评审反馈，将列清单读取和添加列操作放入同一个 `BEGIN IMMEDIATE` 事务。后启动的连接取得写锁后重新读取最新列清单，避免根据旧清单重复添加 `url` 或 `purpose`。

新增真实 SQLite 双连接回归测试：先持有写锁，再让两个独立线程的连接同时到达迁移写入点后释放锁，验证两个连接均能启动，旧任务和支线完整保留，新增列各存在一次。该测试在修复前复现 `duplicate column name: url`，修复后存储、会话、恢复及跨进程相关测试 **49 passed in 2.26s**；`git diff --check` 通过。另在 50 个独立旧库上执行双连接同时打开验证，**50/50 成功**，两条连接读取的原任务和支线均保持一致。Windows 全量 CI 仍以最新工作流结果为准。

## 已知限制及交接

- 本机 macOS 实际操作条件下拉框时发生过两次 `SIGSEGV / EXC_BAD_ACCESS`。系统报告主线程栈涉及 `objc_release`、NSArray 释放与 `libqcocoa.dylib`，没有 Python 层异常；根因尚未确认。记录对应 `Python-2026-11-24-144448.ips` 和 `Python-2026-11-24-150149.ips`。实际条件切换的手动验收未完成，请 A/F 复核。实验条件控件及样式保持原样，不声明该问题已修复。
- 完整自动化通过不代表已覆盖上述 macOS 原生交互崩溃。
- 本提交只交付 C；尚未与 NLP PR #13 联合测试。请 F 集成后核对任务／已确认进度传递、旧上下文分类结果处理及共享 UI／会话代码兼容性。
- 测试使用临时数据库；本地示例数据库和运行日志不应提交。
