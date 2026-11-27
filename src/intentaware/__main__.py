"""Start with `python -m intentaware` or the installed `intentaware` command."""

import argparse
import sys
from pathlib import Path

from intentaware import __version__
from intentaware.config import default_data_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="IntentAware 桌面任务助手（自动识别与人工修正）")
    parser.add_argument("--version", action="version", version=f"IntentAware {__version__}")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--demo", action="store_true", help="用模拟窗口演示自动流程，不读取真实活动")
    modes.add_argument("--manual", action="store_true", help="以暂停自动识别的状态启动，可在界面开启")
    parser.add_argument("--data-dir", type=Path, help="本地数据目录；演示默认使用独立的 demo 子目录")
    parser.add_argument("--condition", choices=("G", "P", "I", "D"), default="D", help="实验条件，默认 D")
    parser.add_argument(
        "--classifier", choices=("local", "llm"), default="local",
        help="活动分类器：local 使用本地规则（默认），llm 调用 INTENTAWARE_LLM_* 配置的兼容服务",
    )
    parser.add_argument(
        "--delegator", choices=("demo", "live"), default="demo",
        help="后台委托：demo 使用离线示例（默认），live 检索最多两份公开来源并调用 LLM 生成答案",
    )
    args = parser.parse_args(argv)

    from PySide6.QtWidgets import QApplication, QMessageBox

    from intentaware.contracts import Condition
    from intentaware.activity.demo import DemoObserver
    from intentaware.activity.monitor import TaskMonitor
    from intentaware.memory.store import SQLiteStore
    from intentaware.session import DesktopSession
    from intentaware.ui.window import MainWindow

    app = QApplication([sys.argv[0]])
    app.setApplicationName("IntentAware")
    app.setOrganizationName("COMP7607-Group14")

    classifier = None
    llm_config = None
    if args.classifier == "llm":
        from intentaware.nlp import LlmActivityClassifier, LlmConfig, NlpError, OpenAICompatibleClient

        try:
            llm_config = LlmConfig.from_env()
            classifier = LlmActivityClassifier(OpenAICompatibleClient(llm_config))
        except NlpError as exc:
            QMessageBox.critical(None, "无法启用 LLM 分类", f"{exc}\n\n未发送任何数据。")
            return 1
        QMessageBox.information(
            None,
            "LLM 分类已启用",
            "主任务、下一步、已确认进度、活动来源和当前活动将发送到：\n"
            f"{llm_config.base_url}\n\n当前活动可能包含前台应用名和窗口标题。\n模型：{llm_config.model}",
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
            QMessageBox.critical(None, "无法启用实时公开检索委托", f"{exc}\n\n未发送任何数据。")
            return 1
        QMessageBox.information(
            None,
            "实时异步委托已启用",
            "用户确认提交的委托问题与备注将发送到：\n"
            f"检索提供方：{delegation_config.search_provider}（最多 {delegation_config.max_sources} 份公开来源）\n"
            f"模型端点：{llm_config.base_url}（模型：{llm_config.model}）\n\n"
            "窗口观察和本地数据库历史不会自动发送。",
        )

    data_dir = args.data_dir or (default_data_dir() / "demo" if args.demo else default_data_dir())
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        store = SQLiteStore(data_dir / "intentaware.sqlite3")
        session = DesktopSession(
            store, classifier=classifier, delegator=delegator, condition=Condition(args.condition)
        )
        monitor = TaskMonitor(
            session, DemoObserver() if args.demo else None,
            enabled=True if args.demo else (False if args.manual else None),
            stable_seconds=0 if args.demo else 3,
        )
    except Exception as exc:
        QMessageBox.critical(None, "无法启动", f"无法打开本地数据目录：\n{data_dir}\n\n{exc}")
        return 1
    window = MainWindow(session, monitor=monitor, demo=args.demo, formulator=formulator)
    app.aboutToQuit.connect(monitor.close)
    app.aboutToQuit.connect(session.close)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
