# C 任务记忆与恢复

[`store.py`](store.py) 的 `SQLiteStore` 保存任务、用户确认的进度、支线、实验事件，以及识别暂停和排除应用设置。自动生成的任务标题会保存在本地，可能包含文件或页面名称；原始持续窗口标题不会逐条写入事件。

点击「修正」后保存会更新同一个当前任务，保留其支线关联。采用新任务建议会创建新的任务标识；旧支线仍归属于旧任务，当前界面只展示当前任务的支线。任务识别与分类不能被当作已确认进度。

[`DesktopSession.resume()`](../session.py) 根据保存的进度与下一步组织恢复提示。用同一数据目录重启，检查任务、进度、支线和设置是否保留。恢复按钮产生 `resume_requested` 事件，研究中的下一次有效主任务编辑需要另行记录。

修改存储后运行 [`test_storage.py`](../../../tests/test_storage.py)；涉及观察设置或任务切换时也运行 [`test_monitor.py`](../../../tests/test_monitor.py)。数据修改与对应事件应在同一事务中提交，失败时整体回滚。

## C 模块完整流程

1. 在工作台点击「修正」，填写主任务、下一步和已确认进度并保存。
2. 进入「支线与恢复」，点击「新增支线」填写笔记，以及可选的 HTTP(S) 链接、用途。也可先从工作台暂存活动，再选中它补充详情。
3. 选中记录后可编辑或删除。编辑不会改变记录 ID、创建时间或所属任务；保存失败会保留编辑内容，以便修正后重试。
4. 恢复提示仅使用已保存的目标、用户确认的进度和下一步，不从窗口行为推断完成情况，也不调用 API。修改任务或进度后提示随之更新；未填写下一步时会明确要求补充。
5. 「忽略本条提示」只忽略当前版本的任务／进度提示；后续修改后提示重新出现。「暂停恢复提示」持续生效直到手动开启。两种设置均跨重启保留，且不影响手动点击「恢复主任务」。该设置与暂停自动窗口识别独立。
6. 使用相同 `--data-dir` 重启，核对任务、进度、笔记、链接、用途和恢复提示设置。G 条件不启用支线及恢复操作；切回 P/I/D 后已保存的内容仍在。

### 接口与数据兼容

- `Detour` 在原有字段后增加默认空字符串字段 `url`、`purpose`，兼容旧构造调用。
- `SQLiteStore` 首次打开旧数据库时追加这两列，不删除或重新创建旧记录；后续启动可重复执行。
- `session.add_detour(text, url="", purpose="")`、`session.update_detour(id, text, url="", purpose="")` 提供新增与修改；`remove_detour(id)` 删除当前任务的记录。
- 链接可留空；填写时必须为有效 HTTP(S) URL，不会自动联网或打开链接。
- 内容变更和事件在同一事务中提交；新增 `detour_updated`、`recovery_ignored`、`recovery_paused`、`recovery_resumed` 事件，事件只含标识／状态，不附支线内容。`resume_requested` 仍不代表有效主任务编辑。

### 本地验收

```bash
python -m pytest
python -m intentaware --manual --condition P --data-dir ./local-memory-data
```

macOS 使用手动模式可完整验收 C，不需要前台采集权限。专项测试为 `tests/test_memory.py`，覆盖旧数据库升级、完整 CRUD、重启、任务隔离、非法输入、提示设置及事务失败；`tests/test_ui.py` 覆盖编辑器与恢复控件。测试使用临时数据库，与日常数据隔离。

`tests/test_memory_process.py` 通过多个独立解释器的退出和启动，验证任务、支线和提示设置的跨进程恢复，以及 G/P/I/D 下的后端功能限制；它不替代真实桌面应用重启和控件切换的手动验收。

[数据目录与测试](../../../docs/GETTING_STARTED.md#本地数据与测试) · [认领与验收](https://github.com/Ir1svanquish/IntentAware-Agent/issues/3)
