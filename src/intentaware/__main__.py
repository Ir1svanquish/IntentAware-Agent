"""Start with `python -m intentaware` or the installed `intentaware` command."""

import argparse
import sys
from pathlib import Path

from intentaware.localization import (
    DEFAULT_LANGUAGE, LANGUAGE_SETTING, LANGUAGES, set_language, tr,
)
from intentaware import __version__
from intentaware.config import default_data_dir


def main(argv: list[str] | None = None) -> int:
    language_options = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    language_options.add_argument("--lang", choices=LANGUAGES)
    language, _ = language_options.parse_known_args(argv)
    set_language(language.lang or DEFAULT_LANGUAGE)

    parser = argparse.ArgumentParser(allow_abbrev=False, description=tr("IntentAware 桌面任务助手（自动识别与人工修正）"))
    parser.add_argument(
        "--lang", choices=LANGUAGES, help=tr("本次运行的界面和反馈语言，默认使用设置中的语言。"),
    )
    parser.add_argument("--version", action="version", version=f"IntentAware {__version__}")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--demo", action="store_true", help=tr("用模拟窗口演示自动流程，不读取真实活动"))
    modes.add_argument("--manual", action="store_true", help=tr("以暂停自动识别的状态启动，可在界面开启"))
    parser.add_argument("--data-dir", type=Path, help=tr("本地数据目录；演示默认使用独立的 demo 子目录"))
    parser.add_argument("--condition", choices=("G", "P", "I", "D"), default="D", help=tr("实验条件，默认 D"))
    parser.add_argument(
        "--classifier", choices=("local", "llm"), default="local",
        help=tr("活动分类器：local 使用本地规则（默认），llm 调用 INTENTAWARE_LLM_* 配置的兼容服务"),
    )
    parser.add_argument(
        "--delegator", choices=("demo", "live"), default="demo",
        help=tr("后台委托：demo 使用离线示例（默认），live 检索最多两份公开来源并调用 LLM 生成答案"),
    )
    args = parser.parse_args(argv)

    from PySide6.QtCore import QLocale, QLockFile, QSettings
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication([sys.argv[0]])
    app.setApplicationName("IntentAware")
    app.setOrganizationName("COMP7607-Group14")
    language = args.lang or QSettings().value(LANGUAGE_SETTING, DEFAULT_LANGUAGE, type=str)
    set_language(language)
    QLocale.setDefault(QLocale("en_US" if language == "en" else "zh_CN"))

    data_dir = args.data_dir or (default_data_dir() / "demo" if args.demo else default_data_dir())
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        database = (data_dir / "intentaware.sqlite3").resolve()
        lock = QLockFile(str(database) + ".lock")
        # The lock belongs to a live process, even if the app has been open for hours.
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            if lock.error() == QLockFile.LockError.LockFailedError:
                QMessageBox.warning(
                    None,
                    tr("数据目录正在使用"),
                    tr(
                        "此数据目录已在另一个 IntentAware 窗口中打开。请切回原窗口，"
                        "或用 --data-dir 指定另一个目录。\n\n{0}",
                        data_dir,
                    ),
                )
                return 1
            raise OSError(tr("无法为数据库创建启动锁，请检查目录的写入权限。"))
    except (OSError, RuntimeError) as exc:
        QMessageBox.critical(None, tr("无法启动"), tr("无法打开本地数据目录：\n{0}\n\n{1}", data_dir, exc))
        return 1

    try:
        return _run_workbench(app, args, data_dir, database)
    finally:
        lock.unlock()


def _run_workbench(app, args: argparse.Namespace, data_dir: Path, database: Path) -> int:
    from PySide6.QtWidgets import QMessageBox

    from intentaware.contracts import Condition
    from intentaware.activity.demo import DemoObserver
    from intentaware.activity.monitor import TaskMonitor
    from intentaware.delegation.demo import DemoDelegator
    from intentaware.memory.store import SQLiteStore
    from intentaware.session import DesktopSession
    from intentaware.ui.window import MainWindow

    classifier = None
    llm_config = None
    if args.classifier == "llm":
        from intentaware.nlp import LlmActivityClassifier, LlmConfig, NlpError, OpenAICompatibleClient

        try:
            llm_config = LlmConfig.from_env()
            classifier = LlmActivityClassifier(OpenAICompatibleClient(llm_config))
        except NlpError as exc:
            QMessageBox.critical(None, tr("无法启用 LLM 分类"), tr("{0}\n\n未发送任何数据。", exc))
            return 1
        QMessageBox.information(
            None,
            tr("LLM 分类已启用"),
            tr(
                "主任务、下一步、已确认进度、活动来源和当前活动将发送到：\n{0}\n\n"
                "当前活动可能包含前台应用名和窗口标题。\n模型：{1}",
                llm_config.base_url,
                llm_config.model,
            ),
        )

    delegator = None
    formulator = None
    if args.delegator == "live":
        from intentaware.delegation import (
            DelegationConfig, DelegationError, LiveDelegator,
            LlmRequestFormulator, LocalRequestFormulator, PublicWebRetriever,
        )
        from intentaware.nlp import LlmConfig, NlpError, OpenAICompatibleClient

        try:
            llm_config = llm_config or LlmConfig.from_env()
            delegation_config = DelegationConfig.from_env()
            delegator = LiveDelegator(
                llm_config,
                PublicWebRetriever(delegation_config),
                config=delegation_config,
            )
            formulator = LlmRequestFormulator(
                OpenAICompatibleClient(llm_config),
                fallback=LocalRequestFormulator(),
            )
        except (NlpError, DelegationError) as exc:
            QMessageBox.critical(None, tr("无法启用实时公开检索委托"), tr("{0}\n\n未发送任何数据。", exc))
            return 1
        QMessageBox.information(
            None,
            tr("实时异步委托已启用"),
            tr(
                "模型端点：{0}（模型：{1}）\n用模型整理时会发送输入的问题及补充的澄清。\n"
                "确认委托后，问题才会发给检索提供方 {2}，最多抓取 {3} 份候选来源。\n"
                "经确认的委托内容和网页摘录会发给模型。委托流程不会自动读取主任务标题、窗口观察或数据库历史。",
                llm_config.base_url,
                llm_config.model,
                delegation_config.search_provider,
                delegation_config.max_sources,
            ),
        )

    if args.demo and delegator is None:
        delegator = DemoDelegator(reference_sample=True)
    try:
        store = SQLiteStore(database)
        session = DesktopSession(
            store, classifier=classifier, delegator=delegator,
            condition=Condition(args.condition), demo_mode=args.demo,
        )
        monitor = TaskMonitor(
            session, DemoObserver() if args.demo else None,
            enabled=True if args.demo else (False if args.manual else None),
            stable_seconds=0 if args.demo else 3,
        )
    except Exception as exc:
        QMessageBox.critical(None, tr("无法启动"), tr("无法打开本地数据目录：\n{0}\n\n{1}", data_dir, exc))
        return 1
    window = MainWindow(session, monitor=monitor, demo=args.demo, formulator=formulator)
    app.aboutToQuit.connect(monitor.close)
    app.aboutToQuit.connect(session.close)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
