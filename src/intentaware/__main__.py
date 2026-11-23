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
            "活动文本（主任务、下一步、已确认进度、当前活动）将发送到：\n"
            f"{llm_config.base_url}\n\n模型：{llm_config.model}",
        )

    data_dir = args.data_dir or (default_data_dir() / "demo" if args.demo else default_data_dir())
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        store = SQLiteStore(data_dir / "intentaware.sqlite3")
        session = DesktopSession(store, classifier=classifier, condition=Condition(args.condition))
        monitor = TaskMonitor(
            session, DemoObserver() if args.demo else None,
            enabled=True if args.demo else (False if args.manual else None),
            stable_seconds=0 if args.demo else 3,
        )
    except Exception as exc:
        QMessageBox.critical(None, "无法启动", f"无法打开本地数据目录：\n{data_dir}\n\n{exc}")
        return 1
    window = MainWindow(session, monitor=monitor, demo=args.demo)
    app.aboutToQuit.connect(monitor.close)
    app.aboutToQuit.connect(session.close)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
