"""Task-first Qt workbench; observations and session updates stay on the UI thread."""

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from html import escape
import re
from sqlite3 import Error as SQLiteError
from typing import TYPE_CHECKING

from PySide6.QtCore import QSettings, QSignalBlocker, QSize, Qt, QTimer
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QPlainTextEdit, QPushButton,
    QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget,
)

from intentaware.localization import DEFAULT_LANGUAGE, LANGUAGE_SETTING, get_language, tr
from intentaware.contracts import ActivityLabel, Condition, DelegationJob, JobStatus
from intentaware.delegation import (
    DelegationDraft, DelegationError, LiveDelegator, LlmRequestFormulator, LocalRequestFormulator,
)
from intentaware.delegation.demo import DEMO_QUESTION
from intentaware.memory.resume import recovery_key, recovery_text
from intentaware.nlp import LlmActivityClassifier, NlpError

from .icons import icon
from .theme import apply_theme

if TYPE_CHECKING:
    from intentaware.activity.monitor import TaskMonitor
    from intentaware.session import DesktopSession


CONDITIONS = {
    Condition.G: "G · 目标提醒",
    Condition.P: "P · 支线暂存与任务恢复",
    Condition.I: "I · 委托完成后立即交付",
    Condition.D: "D · 委托在检查点交付",
}
CONDITION_DESCRIPTIONS = {
    Condition.G: "保留主任务和活动判断，仅提供目标提醒。",
    Condition.P: "保留主任务、暂存临时支线，并在返回时恢复已确认的进度。",
    Condition.I: "支持支线、恢复和离线委托；委托完成后立即显示答案。",
    Condition.D: "支持支线、恢复和离线委托；答案在到达检查点后显示。",
}
CLASSIFICATIONS = {
    ActivityLabel.DIRECT_PROGRESS: "与主任务一致",
    ActivityLabel.NECESSARY_PREPARATION: "在做必要准备",
    ActivityLabel.OPTIONAL_EXPLORATION: "可能是一条支线",
    ActivityLabel.UNCLEAR: "还需要一些线索",
}
ANALYSIS_HINT = "识别到活动后，会自动判断它与主任务的关系。"
RESUME_HINT = "点击“恢复主任务”，查看你上次确认的进度和下一步。"
JOB_STATES = {
    JobStatus.RUNNING: "处理中", JobStatus.READY: "待交付", JobStatus.DELIVERED: "已交付",
    JobStatus.FAILED: "失败", JobStatus.CANCELLED: "已取消",
}
EVENT_NAMES = {
    "session_started": "开始运行", "session_ended": "结束运行", "goal_saved": "保存主任务",
    "analysis_requested": "开始判断活动", "activity_classified": "完成活动判断",
    "analysis_failed": "活动判断失败", "detour_saved": "暂存支线", "detour_removed": "移除支线",
    "distraction_prompted": "显示支线提示", "effective_edit": "确认有效主任务编辑",
    "resume_requested": "恢复主任务", "delegation_submitted": "提交委托",
    "delegation_completed": "完成委托", "delegation_delivered": "交付答案",
    "delegation_failed": "委托失败", "delegation_cancelled": "取消委托",
    "checkpoint_reached": "到达检查点", "task_inferred": "自动识别任务",
    "task_corrected": "修正任务", "task_adopted": "采用任务建议",
    "observation_paused": "暂停自动识别", "observation_resumed": "恢复自动识别",
    "app_excluded": "排除应用", "exclusions_updated": "更新排除列表",
    "activity_observed": "更新窗口线索",
    "detour_updated": "编辑支线", "recovery_ignored": "忽略恢复提示",
    "recovery_paused": "暂停恢复提示", "recovery_resumed": "开启恢复提示",
}
UI_ERRORS = (ValueError, RuntimeError, SQLiteError, OSError, DelegationError, NlpError)
ROW_ID = Qt.ItemDataRole.UserRole
WORKBENCH, DETOURS, DELEGATION, EXPERIMENTS, SETTINGS = range(5)
PAGES = (
    ("工作台", "留住主任务，接着往下做。", "workspace"),
    ("支线与恢复", "把临时想法放在这里，随时接回主任务。", "detours"),
    ("委托", "把一个问题交给后台，继续手头的工作。", "delegation"),
    ("实验与记录", "切换实验条件，查看并导出本次运行。", "experiment"),
    ("设置", "选择语言，管理自动识别和应用排除。", "settings"),
)


def _label(text: str = "", role: str = "", *, wrap: bool = False) -> QLabel:
    label = QLabel(text)
    label.setTextFormat(Qt.TextFormat.PlainText)
    if role:
        label.setProperty("role", role)
    if wrap:
        label.setWordWrap(True)
        label.setMinimumWidth(0)
        label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
    return label


def _field(layout: QVBoxLayout, caption: str, widget: QWidget) -> None:
    label = _label(caption, "field")
    label.setBuddy(widget)
    widget.setAccessibleName(caption)
    layout.addWidget(label)
    layout.addWidget(widget)


def _button(text: str, on_click: Callable[[], None], *, primary: bool = False,
            quiet: bool = False, glyph: str | None = None) -> QPushButton:
    button = QPushButton(text)
    button.setProperty("primary", primary)
    button.setProperty("quiet", quiet)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    if glyph:
        button.setIcon(icon(glyph, "#FFFFFF" if primary else "#606B80", 16))
        button.setIconSize(QSize(16, 16))
    button.clicked.connect(on_click)
    return button


def _card(title: str = "", name: str = "card") -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName(name)
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    if title:
        layout.addWidget(_label(title, "heading"))
    return frame, layout


def _badge(label: QLabel, text: str, tone: str = "") -> None:
    label.setText(text)
    if label.property("tone") != tone:
        label.setProperty("tone", tone)
        label.style().unpolish(label)
        label.style().polish(label)


def _preview(label: QLabel, text: str, limit: int = 180) -> None:
    preview = text if len(text) <= limit else text[:limit].rstrip() + "…"
    # QLabel cannot wrap a single long path/identifier. Explicit ellipses keep
    # the card within the viewport; the complete source remains in its tooltip
    # and the editable field, without adding invisible characters to copied text.
    preview = re.sub(r"[A-Za-z0-9_./:\\-]{40,}", lambda match: match[0][:16] + " … " + match[0][-12:], preview)
    label.setText(preview)
    label.setToolTip(f"<p>{escape(text)}</p>" if text else "")


def _selected_id(widget: QListWidget) -> str | None:
    item = widget.currentItem()
    return item.data(ROW_ID) if item else None


def _sync_rows(widget: QListWidget, rows: list[tuple[str, str]], select: str | None = None) -> None:
    selected = select or _selected_id(widget)
    old = [(widget.item(i).data(ROW_ID), widget.item(i).text()) for i in range(widget.count())]
    with QSignalBlocker(widget):
        if old != rows:
            widget.clear()
            for row_id, text in rows:
                item = QListWidgetItem(text)
                item.setData(ROW_ID, row_id)
                item.setToolTip(f"<p>{escape(text)}</p>")
                widget.addItem(item)
        if selected is not None:
            for i, (row_id, _) in enumerate(rows):
                if row_id == selected:
                    widget.setCurrentRow(i)
                    break


class MainWindow(QMainWindow):
    def __init__(self, session: "DesktopSession", monitor: "TaskMonitor | None" = None,
                 demo: bool = False, formulator=None) -> None:
        super().__init__()
        self.session = session
        self.monitor = monitor
        self.demo = demo
        self.formulator = formulator if formulator is not None else LocalRequestFormulator()
        self._uses_llm = isinstance(session.classifier, LlmActivityClassifier)
        self._uses_live_delegator = isinstance(session.delegator, LiveDelegator)
        self._draft_executor = (
            ThreadPoolExecutor(max_workers=1, thread_name_prefix="delegation-draft")
            if isinstance(self.formulator, LlmRequestFormulator) else None
        )
        self._draft_future: Future[DelegationDraft] | None = None
        self._analyzed_activity: str | None = None
        self._distraction_prompt = None
        self._recorded_distraction_prompt = None
        self._manual_observation_key: tuple[str, str] | None = None
        self._editing_goal = False
        self._exclusions_dirty = False
        self._editing_detour_id: str | None = None
        self._detour_editor_goal_id: str | None = None
        self._draft: DelegationDraft | None = None
        self._draft_goal_id: str | None = None
        self._resume_requested_key: str | None = None
        self._closed = False
        self.setWindowTitle(tr("IntentAware · 任务工作台"))
        self.resize(1160, 800)
        self.setMinimumSize(900, 650)
        self._build()
        apply_theme(self)
        self._load_goal()
        self._refresh()
        self._show_page(WORKBENCH)
        self._status(self._startup_status())
        self._timer = QTimer(self, interval=100)
        self._timer.timeout.connect(self._poll)
        self._timer.start()

    def _build(self) -> None:
        root = QWidget()
        root.setObjectName("workbench")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setCentralWidget(root)
        layout.addWidget(self._build_sidebar())

        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        layout.addLayout(content, 1)
        header = QFrame()
        header.setObjectName("pageHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(28, 25, 28, 22)
        header_row.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(5)
        self.page_title = _label()
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = _label(wrap=True)
        self.page_subtitle.setObjectName("pageSubtitle")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        header_row.addLayout(titles, 1)
        self.monitor_status = _label(role="badge")
        self.monitor_status.setAccessibleName(tr("自动识别状态"))
        self.pause_button = _button(tr("暂停识别"), self._toggle_monitor, glyph="pause")
        header_row.addWidget(self.monitor_status, alignment=Qt.AlignmentFlag.AlignVCenter)
        header_row.addWidget(self.pause_button, alignment=Qt.AlignmentFlag.AlignVCenter)
        content.addWidget(header)

        self.pages = QStackedWidget()
        for builder in (self._build_workbench, self._build_detours, self._build_delegation,
                        self._build_experiments, self._build_settings):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(builder())
            self.pages.addWidget(scroll)
        content.addWidget(self.pages, 1)

        footer = QFrame()
        footer.setObjectName("footer")
        footer_row = QHBoxLayout(footer)
        footer_row.setContentsMargins(28, 8, 28, 8)
        self.status_label = _label(wrap=True)
        self.status_label.setObjectName("status_label")
        self.status_label.setAccessibleName(tr("操作反馈"))
        footer_row.addWidget(self.status_label)
        content.addWidget(footer)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(232 if get_language() == "en" else 204)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(16, 30, 16, 23)
        layout.setSpacing(6)
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(8, 0, 0, 0)
        brand_row.setSpacing(9)
        mark = _label()
        mark.setPixmap(icon("workspace", "#CCD4FF", 24).pixmap(24, 24))
        mark.setFixedSize(24, 24)
        brand = _label("IntentAware")
        brand.setObjectName("brand")
        brand_row.addWidget(mark)
        brand_row.addWidget(brand)
        brand_row.addStretch()
        layout.addLayout(brand_row)
        caption = _label(tr("    让注意力回到眼前的任务"))
        caption.setObjectName("brandCaption")
        layout.addWidget(caption)
        layout.addSpacing(38)
        section = _label(tr("    工作空间"))
        section.setObjectName("sidebarSection")
        layout.addWidget(section)
        layout.addSpacing(5)
        self.nav_group = QButtonGroup(self)
        self.nav_buttons = []
        for index, (title, _, glyph) in enumerate(PAGES):
            title = tr(title)
            button = QPushButton("  " + title.replace("&", "&&"))
            button.setProperty("nav", True)
            button.setCheckable(True)
            button.setIcon(icon(glyph, "#C8D1E3", 19))
            button.setIconSize(QSize(19, 19))
            button.setAccessibleName(title)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda checked=False, index=index: self._show_page(index))
            self.nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            if index == EXPERIMENTS:
                layout.addSpacing(24)
                section = _label(tr("    偏好与工具"))
                section.setObjectName("sidebarSection")
                layout.addWidget(section)
                layout.addSpacing(5)
            layout.addWidget(button)
        (self.workbench_nav, self.detours_nav, self.delegation_nav,
         self.experiment_nav, self.settings_nav) = self.nav_buttons
        layout.addStretch()
        layout.addSpacing(24)
        mode_row = QHBoxLayout()
        mode_row.setContentsMargins(8, 0, 0, 0)
        mode_row.setSpacing(8)
        shield = _label()
        shield.setPixmap(icon("shield", "#AFC4D2", 18).pixmap(18, 18))
        mode = _label(tr("演示模式") if self.demo else (tr("LLM 分类模式") if self._uses_llm else tr("本地工作空间")))
        mode.setObjectName("sidebarMode")
        mode_row.addWidget(shield)
        mode_row.addWidget(mode)
        mode_row.addStretch()
        layout.addLayout(mode_row)
        note = _label(tr("    活动文本发送到模型端点") if self._uses_llm else tr("    窗口标题在本机处理"))
        note.setObjectName("sidebarFootnote")
        layout.addWidget(note)
        return sidebar

    @staticmethod
    def _page() -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        page.setObjectName("canvas")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 0, 28, 24)
        layout.setSpacing(16)
        return page, layout

    def _build_workbench(self) -> QWidget:
        page, layout = self._page()
        self.task_card, task = _card(name="taskCard")
        header = QHBoxLayout()
        header.setSpacing(10)
        header.addWidget(_label(tr("当前主任务"), "eyebrow"))
        self.goal_origin_label = _label(role="badge")
        header.addWidget(self.goal_origin_label)
        header.addStretch()
        self.correction_button = _button(tr("修正"), self._edit_goal, quiet=True, glyph="edit")
        header.addWidget(self.correction_button)
        task.addLayout(header)

        self.task_display = QWidget()
        display = QVBoxLayout(self.task_display)
        display.setContentsMargins(0, 0, 0, 0)
        display.setSpacing(15)
        self.task_title = _label(wrap=True)
        self.task_title.setObjectName("taskTitle")
        self.task_title.setAccessibleName(tr("当前主任务"))
        self.task_title.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        display.addWidget(self.task_title)
        next_step = QFrame()
        next_step.setObjectName("nextStep")
        next_layout = QVBoxLayout(next_step)
        next_layout.setContentsMargins(16, 12, 16, 13)
        next_layout.setSpacing(5)
        next_layout.addWidget(_label(tr("接下来"), "eyebrow"))
        self.task_next_step = _label(wrap=True)
        self.task_next_step.setObjectName("taskNextStep")
        next_layout.addWidget(self.task_next_step)
        display.addWidget(next_step)
        self.progress_label = _label(role="muted", wrap=True)
        display.addWidget(self.progress_label)
        task.addWidget(self.task_display)
        task.addWidget(self._build_correction_editor())
        layout.addWidget(self.task_card)

        self.suggestion_card, suggestion = _card(name="suggestionCard")
        suggestion.addWidget(_label(tr("发现另一项可能的任务"), "eyebrow"))
        suggestion_row = QHBoxLayout()
        suggestion_row.setSpacing(18)
        suggestion_text = QVBoxLayout()
        suggestion_text.setSpacing(5)
        self.suggestion_title = _label(wrap=True)
        self.suggestion_title.setObjectName("suggestionTitle")
        self.suggestion_reason = _label(role="body", wrap=True)
        suggestion_text.addWidget(self.suggestion_title)
        suggestion_text.addWidget(self.suggestion_reason)
        suggestion_row.addLayout(suggestion_text, 1)
        suggestion_actions = QHBoxLayout()
        suggestion_actions.setSpacing(8)
        self.dismiss_suggestion_button = _button(tr("暂不切换"), self._dismiss_suggestion, quiet=True)
        self.adopt_suggestion_button = _button(tr("切换到此任务"), self._adopt_suggestion, primary=True)
        suggestion_actions.addWidget(self.dismiss_suggestion_button)
        suggestion_actions.addWidget(self.adopt_suggestion_button)
        suggestion_row.addLayout(suggestion_actions)
        suggestion.addLayout(suggestion_row)
        layout.addWidget(self.suggestion_card)

        observations = QHBoxLayout()
        observations.setSpacing(16)
        activity_card, activity = _card()
        activity_header = QHBoxLayout()
        activity_header.addWidget(_label(tr("当前活动"), "heading"))
        activity_header.addStretch()
        self.activity_state = _label(role="badge")
        activity_header.addWidget(self.activity_state)
        activity.addLayout(activity_header)
        self.activity_label = _label(wrap=True)
        self.activity_label.setObjectName("activityTitle")
        self.activity_label.setAccessibleName(tr("识别到的活动"))
        self.activity_source = _label(role="muted", wrap=True)
        self.window_title_label = _label(role="body", wrap=True)
        self.window_title_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        activity.addWidget(self.activity_label)
        activity.addWidget(self.activity_source)
        activity.addWidget(self.window_title_label)
        activity.addStretch()
        self.confidence_label = _label(role="badge")
        activity.addWidget(self.confidence_label, alignment=Qt.AlignmentFlag.AlignLeft)
        self.recognition_reason = _label(role="muted", wrap=True)
        activity.addWidget(self.recognition_reason)
        observations.addWidget(activity_card, 6)

        relation_card, relation = _card(tr("与主任务的关系"))
        self.classification_title = _label(wrap=True)
        self.classification_title.setObjectName("classificationTitle")
        self.classification_label = _label(role="body", wrap=True)
        self.classification_label.setAccessibleName(tr("活动分类结果"))
        self.classification_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        relation.addWidget(self.classification_title)
        relation.addWidget(self.classification_label)
        relation.addStretch()
        self.detour_button = _button(tr("暂存此活动"), self._add_detour, glyph="detours")
        relation.addWidget(self.detour_button, alignment=Qt.AlignmentFlag.AlignLeft)
        observations.addWidget(relation_card, 5)
        layout.addLayout(observations)

        self.manual_toggle = _button(tr("手动补充活动"), self._toggle_manual, quiet=True, glyph="chevron")
        self.manual_toggle.setObjectName("manualToggle")
        self.manual_toggle.setCheckable(True)
        layout.addWidget(self.manual_toggle, alignment=Qt.AlignmentFlag.AlignLeft)
        self.manual_panel, manual = _card()
        self.activity_input = QPlainTextEdit(placeholderText=tr("标题线索不足时，补充你正在做的事情。"))
        self.activity_input.setFixedHeight(94)
        self.activity_input.textChanged.connect(self._manual_activity_changed)
        _field(manual, tr("活动描述"), self.activity_input)
        actions = QHBoxLayout()
        self.analyze_button = _button(tr("分析这段活动"), self._analyze, primary=True)
        self.manual_detour_button = _button(tr("暂存为支线"), lambda: self._add_detour(manual=True))
        actions.addWidget(self.analyze_button)
        actions.addWidget(self.manual_detour_button)
        actions.addStretch()
        manual.addLayout(actions)
        self.manual_classification_label = _label(role="body", wrap=True)
        manual.addWidget(self.manual_classification_label)
        self.manual_panel.hide()
        layout.addWidget(self.manual_panel)
        layout.addStretch()
        return page

    def _build_correction_editor(self) -> QWidget:
        self.correction_editor = QWidget()
        layout = QVBoxLayout(self.correction_editor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        self.goal_input = QLineEdit(placeholderText=tr("你希望完成什么？"))
        self.next_step_input = QLineEdit(placeholderText=tr("下一项可以着手的具体动作"))
        self.progress_input = QLineEdit(placeholderText=tr("只写下已经完成并确认的进度"))
        self.goal_edit, self.next_step_edit, self.progress_edit = self.goal_input, self.next_step_input, self.progress_input
        for caption, field in ((tr("主任务"), self.goal_input), (tr("下一步"), self.next_step_input),
                               (tr("已确认进度（可选）"), self.progress_input)):
            _field(layout, caption, field)
            field.returnPressed.connect(self._save_goal)
        self.correction_error = _label(role="error", wrap=True)
        self.correction_error.hide()
        layout.addWidget(self.correction_error)
        actions = QHBoxLayout()
        actions.setContentsMargins(0, 6, 0, 0)
        self.save_goal_button = _button(tr("保存修正"), self._save_goal, primary=True)
        self.cancel_correction_button = _button(tr("取消"), self._cancel_correction)
        actions.addWidget(self.save_goal_button)
        actions.addWidget(self.cancel_correction_button)
        actions.addStretch()
        layout.addLayout(actions)
        self.correction_editor.hide()
        return self.correction_editor

    def _build_detours(self) -> QWidget:
        page, layout = self._page()
        self.detour_unavailable = _label(tr("当前 G 条件未启用支线记忆。可在“实验与记录”中切换条件。"), "notice", wrap=True)
        layout.addWidget(self.detour_unavailable)
        panel, items = _card(tr("暂存的活动"))
        self.detour_hint = _label(role="muted", wrap=True)
        items.addWidget(self.detour_hint)
        self.detour_list = QListWidget(wordWrap=True)
        self.detour_list.setAccessibleName(tr("已暂存支线"))
        self.detour_list.setMinimumHeight(180)
        self.detour_list.currentRowChanged.connect(self._refresh_detour_actions)
        items.addWidget(self.detour_list)
        self.detour_empty = _label(tr("目前没有支线\n\n在工作台点击“暂存此活动”，把临时想法留到稍后。"), "muted", wrap=True)
        self.detour_empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detour_empty.setMinimumHeight(150)
        items.addWidget(self.detour_empty)
        actions = QHBoxLayout()
        self.new_detour_button = _button(tr("新增支线"), lambda: self._edit_detour(new=True))
        self.edit_detour_button = _button(tr("编辑选中支线"), self._edit_detour)
        self.remove_detour_button = _button(tr("删除选中支线"), self._remove_detour)
        for button in (self.new_detour_button, self.edit_detour_button, self.remove_detour_button):
            actions.addWidget(button)
        actions.addStretch()
        items.addLayout(actions)
        self.detour_editor, editor = _card(tr("支线内容"))
        self.detour_text_input = QPlainTextEdit()
        self.detour_text_input.setMaximumHeight(100)
        self.detour_url_input = QLineEdit(placeholderText=tr("https://…（可留空）"))
        self.detour_purpose_input = QLineEdit(placeholderText=tr("为什么保存它，准备什么时候再看？（可留空）"))
        _field(editor, tr("笔记"), self.detour_text_input)
        _field(editor, tr("链接"), self.detour_url_input)
        _field(editor, tr("用途"), self.detour_purpose_input)
        self.detour_error = _label(role="error", wrap=True)
        editor.addWidget(self.detour_error)
        buttons = QHBoxLayout()
        self.save_detour_button = _button(tr("保存支线"), self._save_detour, primary=True)
        self.cancel_detour_button = _button(tr("取消编辑"), self._cancel_detour_edit)
        buttons.addWidget(self.save_detour_button)
        buttons.addWidget(self.cancel_detour_button)
        buttons.addStretch()
        editor.addLayout(buttons)
        self.detour_editor.hide()
        items.addWidget(self.detour_editor)
        layout.addWidget(panel)
        panel, resume = _card(tr("接回主任务"))
        self.resume_label = _label(tr(RESUME_HINT), "body", wrap=True)
        self.resume_label.setAccessibleName(tr("任务恢复提示"))
        self.resume_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        resume.addWidget(self.resume_label)
        self.resume_button = _button(tr("恢复主任务"), self._resume, primary=True, glyph="arrow")
        actions = QHBoxLayout()
        self.ignore_recovery_button = _button(tr("忽略本条提示"), self._ignore_recovery)
        self.pause_recovery_button = _button(tr("暂停恢复提示"), self._toggle_recovery)
        for button in (self.resume_button, self.ignore_recovery_button, self.pause_recovery_button):
            actions.addWidget(button)
        actions.addStretch()
        resume.addLayout(actions)
        layout.addWidget(panel)
        layout.addStretch()
        return page

    def _build_delegation(self) -> QWidget:
        page, layout = self._page()
        self.delegation_unavailable = _label(tr("当前条件未启用委托。可在“实验与记录”中切换到 I 或 D。"), "notice", wrap=True)
        layout.addWidget(self.delegation_unavailable)
        panel, delegation = _card()
        heading = QHBoxLayout()
        heading.addWidget(_label(tr("交给后台的问题"), "heading"))
        heading.addStretch()
        self.delegation_badge = _label(
            tr("公开检索 · LLM") if self._uses_live_delegator else tr("离线演示"),
            "badge",
        )
        if self._uses_live_delegator:
            self.delegation_badge.setProperty("tone", "accent")
        heading.addWidget(self.delegation_badge)
        delegation.addLayout(heading)
        self.delegation_mode_hint = _label(
            tr("先整理可编辑请求，确认后再检索最多两份公开来源。")
            if self._uses_live_delegator
            else tr("当前使用离线示例回答，用于验证委托与交付流程。"),
            "muted",
            wrap=True,
        )
        delegation.addWidget(self.delegation_mode_hint)
        if self._draft_executor is not None:
            delegation.addWidget(_label(
                tr("点击「用模型整理」或按回车会向配置的模型发送输入的问题。补充澄清时也会发送所填内容。"),
                "muted", wrap=True,
            ))
        controls = QHBoxLayout()
        self.question_input = QLineEdit(placeholderText=tr("例如：被打断后，怎样更快恢复当前任务？"))
        self.question_input.setAccessibleName(tr("委托问题"))
        self.question_input.returnPressed.connect(self._submit)
        controls.addWidget(self.question_input, 1)
        self.formulate_button = _button(
            tr("用模型整理") if self._draft_executor is not None else tr("整理请求"), self._formulate
        )
        controls.addWidget(self.formulate_button)
        self.submit_button = _button(tr("提交委托"), self._submit, primary=True)
        self.submit_button.setVisible(not self._uses_live_delegator)
        controls.addWidget(self.submit_button)
        delegation.addLayout(controls)

        self.draft_editor = QFrame()
        self.draft_editor.setObjectName("editorBox")
        draft_layout = QVBoxLayout(self.draft_editor)
        draft_layout.setContentsMargins(16, 14, 16, 14)
        draft_layout.setSpacing(10)
        draft_layout.addWidget(_label(tr("可编辑委托请求（确认后提交给后台）"), "heading"))
        self.draft_question_input = QLineEdit(placeholderText=tr("整理后的明确问题"))
        _field(draft_layout, tr("明确问题"), self.draft_question_input)
        self.draft_scope_input = QLineEdit(placeholderText=tr("例如：只核对文件兼容性与免费版限制"))
        _field(draft_layout, tr("处理范围"), self.draft_scope_input)
        self.draft_output_input = QLineEdit(placeholderText=tr("例如：简短结论、来源链接及未解决点"))
        _field(draft_layout, tr("期望输出"), self.draft_output_input)

        self.clarification_box = QFrame()
        clarify_layout = QVBoxLayout(self.clarification_box)
        clarify_layout.setContentsMargins(0, 4, 0, 4)
        clarify_layout.setSpacing(6)
        self.clarification_label = _label("", "notice", wrap=True)
        clarify_layout.addWidget(self.clarification_label)
        clarify_row = QHBoxLayout()
        self.clarification_input = QLineEdit(placeholderText=tr("补充澄清说明（最多一次，也可直接确认提交）"))
        self.clarification_input.setAccessibleName(tr("澄清说明"))
        clarify_row.addWidget(self.clarification_input, 1)
        self.apply_clarification_button = _button(
            tr("发送澄清并重新整理") if self._draft_executor is not None else tr("补充并重新整理"),
            self._apply_clarification,
        )
        clarify_row.addWidget(self.apply_clarification_button)
        clarify_layout.addLayout(clarify_row)
        self.clarification_box.hide()
        draft_layout.addWidget(self.clarification_box)

        draft_actions = QHBoxLayout()
        self.confirm_draft_button = _button(tr("确认并提交委托"), self._confirm_draft, primary=True)
        self.cancel_draft_button = _button(
            tr("取消整理"), lambda: self._perform(self._cancel_draft), quiet=True
        )
        draft_actions.addWidget(self.confirm_draft_button)
        draft_actions.addWidget(self.cancel_draft_button)
        draft_actions.addStretch()
        draft_layout.addLayout(draft_actions)
        self.draft_editor.hide()
        delegation.addWidget(self.draft_editor)

        self.job_list = QListWidget()
        self.job_list.setAccessibleName(tr("委托列表"))
        self.job_list.setFixedHeight(112)
        self.job_list.currentItemChanged.connect(self._refresh_job_result)
        delegation.addWidget(self.job_list)
        self.job_empty = _label(tr("还没有委托。提交一个问题后，可以继续在其他页面工作。"), "muted", wrap=True)
        delegation.addWidget(self.job_empty)
        layout.addWidget(panel)
        panel, result = _card(tr("答案与交付"))
        self.job_result = QPlainTextEdit(readOnly=True, placeholderText=tr("选择一项委托查看状态，已交付的答案会显示在这里。"))
        self.job_result.setAccessibleName(tr("委托结果"))
        self.job_result.setMinimumHeight(136)
        result.addWidget(self.job_result)
        actions = QHBoxLayout()
        self.checkpoint_label_input = QLineEdit(placeholderText=tr("可选节点说明，例如：写完本段"))
        self.checkpoint_label_input.setAccessibleName(tr("检查点说明"))
        actions.addWidget(self.checkpoint_label_input, 1)
        self.checkpoint_button = _button(tr("到达检查点"), self._checkpoint, primary=True)
        self.reveal_button = _button(tr("提前查看"), self._reveal)
        self.cancel_button = _button(tr("取消委托"), self._cancel)
        actions.addWidget(self.checkpoint_button)
        actions.addWidget(self.reveal_button)
        actions.addWidget(self.cancel_button)
        result.addLayout(actions)
        layout.addWidget(panel)
        layout.addStretch()
        return page

    def _build_experiments(self) -> QWidget:
        page, layout = self._page()
        panel, settings = _card(tr("实验条件"))
        self.condition_combo = QComboBox()
        for condition, text in CONDITIONS.items():
            self.condition_combo.addItem(tr(text), condition.value)
        self.condition_combo.currentIndexChanged.connect(self._change_condition)
        _field(settings, tr("当前条件"), self.condition_combo)
        self.condition_description = _label(role="body", wrap=True)
        settings.addWidget(self.condition_description)
        settings.addWidget(_label(tr("切换条件会开始新一轮记录。先完成或取消仍在处理、等待交付的委托。"), "muted", wrap=True))
        layout.addWidget(panel)
        panel, events = _card()
        header = QHBoxLayout()
        header.addWidget(_label(tr("本次运行记录"), "heading"))
        header.addStretch()
        self.export_button = _button(tr("导出 JSONL"), self._export, glyph="download")
        header.addWidget(self.export_button)
        events.addLayout(header)
        events.addWidget(_label(tr("本地事件记录 · 时间为 UTC"), "muted"))
        self.effective_edit_button = _button(tr("记录有效主任务编辑"), self._record_effective_edit)
        self.effective_edit_button.setToolTip(tr("研究者实际观察到参与者继续编辑主任务后再记录。"))
        events.addWidget(self.effective_edit_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.event_list = QListWidget()
        self.event_list.setAccessibleName(tr("本次运行事件"))
        self.event_list.setMinimumHeight(200)
        events.addWidget(self.event_list)
        layout.addWidget(panel)
        panel, demo = _card(tr("演示示例"))
        demo.addWidget(_label(tr("填入一组示例输入，尝试支线和离线委托。示例不会自动保存。"), "body", wrap=True))
        self.sample_button = _button(tr("填入演示示例"), self._fill_sample)
        demo.addWidget(self.sample_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(panel)
        layout.addStretch()
        return page

    def _build_settings(self) -> QWidget:
        page, layout = self._page()
        panel, language = _card(tr("语言"))
        self.language_combo = QComboBox()
        self.language_combo.addItem(tr("简体中文"), "zh")
        self.language_combo.addItem("English", "en")
        saved_language = QSettings().value(LANGUAGE_SETTING, DEFAULT_LANGUAGE, type=str)
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(saved_language)))
        self.language_combo.activated.connect(self._save_language)
        _field(language, tr("界面语言"), self.language_combo)
        self.language_status = _label(tr("界面和反馈将在重启后切换语言。"), "muted", wrap=True)
        language.addWidget(self.language_status)
        layout.addWidget(panel)
        panel, monitor = _card(tr("自动任务识别"))
        if self._uses_llm:
            hint = (tr("活动分类会将主任务、下一步、已确认进度、活动来源和当前活动发送到已配置的模型端点。当前活动可能包含前台应用名和窗口标题。主任务可随时修正。"))
        else:
            hint = tr("根据前台应用名和窗口标题，在本机推断当前任务。主任务可随时修正。")
        monitor.addWidget(_label(hint, "body", wrap=True))
        self.settings_monitor_status = _label(role="muted", wrap=True)
        monitor.addWidget(self.settings_monitor_status)
        line = QFrame()
        line.setObjectName("line")
        line.setFixedHeight(1)
        monitor.addWidget(line)
        row = QHBoxLayout()
        row.setSpacing(16)
        self.current_app_label = _label(role="body", wrap=True)
        row.addWidget(self.current_app_label, 1)
        self.exclude_current_button = _button(tr("排除当前应用"), self._exclude_current_app)
        row.addWidget(self.exclude_current_button)
        monitor.addLayout(row)
        layout.addWidget(panel)
        panel, exclusions = _card(tr("不观察的应用"))
        exclusions.addWidget(_label(tr("每行一个应用名称，与识别到的应用名称一致。保存后立即生效。"), "muted", wrap=True))
        self.excluded_apps_input = QPlainTextEdit(placeholderText=tr("例如：\nKeePassXC\n1Password"))
        self.excluded_apps_input.setAccessibleName(tr("排除的应用名称，每行一个"))
        self.excluded_apps_input.setFixedHeight(116)
        self.excluded_apps_input.textChanged.connect(self._mark_exclusions_dirty)
        exclusions.addWidget(self.excluded_apps_input)
        self.save_exclusions_button = _button(tr("保存排除列表"), self._save_exclusions, primary=True)
        exclusions.addWidget(self.save_exclusions_button, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(panel)
        privacy = _label(tr("前台观察只读取应用名称和窗口标题。\n可随时暂停自动识别或在此排除应用。"), "muted", wrap=True)
        layout.addWidget(privacy)
        layout.addStretch()
        return page

    def _save_language(self, index: int) -> None:
        settings = QSettings()
        settings.setValue(LANGUAGE_SETTING, self.language_combo.itemData(index))
        settings.sync()
        if settings.status() != settings.Status.NoError:
            self.language_status.setText(tr("无法保存语言设置。"))
        else:
            self.language_status.setText(tr("已保存语言设置，重启后生效。"))

    def _show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        self.page_title.setText(tr(PAGES[index][0]))
        self.page_subtitle.setText(tr(PAGES[index][1]))

    def _load_goal(self) -> None:
        if self._editing_goal:
            return
        goal = self.session.goal
        self.goal_input.setText(goal.title if goal else "")
        self.next_step_input.setText(goal.next_step if goal else "")
        self.progress_input.setText(self.session.progress.note if self.session.progress else "")

    def _startup_status(self) -> str:
        if self._uses_llm:
            return tr("LLM 分类会把活动文本（可能含窗口标题）和主任务信息发送到已配置的模型端点。")
        if self.monitor:
            return tr("自动识别只使用本机的应用名称与窗口标题。")
        return tr("手动模式 · 可修正主任务，或展开手动补充活动。")

    def _status(self, text: str = "", *, error: bool = False) -> None:
        self.status_label.setText(text)
        self.status_label.setProperty("error", error)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)

    def _perform(self, action: Callable[[], str | None]) -> bool:
        try:
            message = action()
            self._refresh()
        except UI_ERRORS as error:
            self._status(str(error), error=True)
            return False
        self._status(message or "")
        return True

    def _edit_goal(self) -> None:
        self._show_page(WORKBENCH)
        self._load_goal()
        self._editing_goal = True
        self.correction_error.hide()
        self.task_display.hide()
        self.correction_editor.show()
        self.correction_button.hide()
        self._refresh_task()
        self.goal_input.setFocus()
        self.goal_input.selectAll()

    def _cancel_correction(self) -> None:
        self._editing_goal = False
        self.correction_editor.hide()
        self.task_display.show()
        self.correction_button.show()
        self._load_goal()
        self._refresh_task()
        self.correction_button.setFocus()
        QTimer.singleShot(0, lambda: self.pages.widget(WORKBENCH).verticalScrollBar().setValue(0))

    def _fill_sample(self) -> None:
        self._edit_goal()
        if self.demo and not self._uses_live_delegator:
            self.goal_input.setText(tr("完成命令行校验功能"))
            self.next_step_input.setText(tr("补齐错误提示并运行测试"))
            self.progress_input.setText(tr("已实现参数解析"))
            self.activity_input.setPlainText(tr("顺便研究 argparse 的可选参数怎么设为必填。"))
            self.question_input.setText(tr(DEMO_QUESTION))
        else:
            self.goal_input.setText(tr("完成研究报告初稿"))
            self.next_step_input.setText(tr("整理三篇文献，写出方法章节的提纲"))
            self.progress_input.setText(tr("已确定研究问题，收集了三篇参考文献"))
            self.activity_input.setPlainText(tr("顺便浏览了一些演示文稿模板，想保存下来以后参考。"))
            self.question_input.setText(tr("被打断后，怎样更快地恢复当前任务？"))
        self.manual_toggle.setChecked(True)
        self._toggle_manual()
        self._status(tr("已填入示例。保存修正后，可以分析示例活动或提交离线委托。"))

    def _save_goal(self) -> None:
        def save() -> str:
            method = self.monitor.correct_task if self.monitor else self.session.set_goal
            method(self.goal_input.text(), self.next_step_input.text(), self.progress_input.text())
            self._analyzed_activity = None
            self.resume_label.setText(tr(RESUME_HINT))
            self._cancel_correction()
            return tr("已保存主任务、下一步和已确认进度。")

        if not self._perform(save):
            self.correction_error.setText(self.status_label.text())
            self.correction_error.show()
            if not self.goal_input.text().strip():
                self.goal_input.setFocus()

    def _toggle_manual(self) -> None:
        opened = self.manual_toggle.isChecked()
        self.manual_panel.setVisible(opened)
        self.manual_toggle.setIcon(icon("chevron_up" if opened else "chevron", size=16))
        self.manual_toggle.setAccessibleDescription(tr("已展开") if opened else tr("已折叠"))
        if opened:
            self.activity_input.setFocus()

    def _manual_activity_changed(self) -> None:
        if not hasattr(self, "manual_classification_label"):
            return
        self._refresh_classification()
        pending = self.session.analysis_pending
        self.manual_detour_button.setEnabled(self.session.memory_enabled and not pending
                                            and bool(self.activity_input.toPlainText().strip())
                                            and self.session.goal is not None)
        if not self.monitor:
            self._refresh_activity()
            self.detour_button.setEnabled(self.manual_detour_button.isEnabled())

    def _toggle_monitor(self) -> None:
        if self.monitor:
            def toggle() -> str:
                self.monitor.pause() if self.monitor.enabled else self.monitor.resume()
                return self.monitor.message
            self._perform(toggle)

    def _adopt_suggestion(self) -> None:
        if self.monitor:
            def adopt() -> str:
                self.monitor.adopt_suggestion()
                self._load_goal()
                self.resume_label.setText(tr(RESUME_HINT))
                return tr("已切换到这项任务。")
            if self._perform(adopt):
                self.correction_button.setFocus()

    def _dismiss_suggestion(self) -> None:
        if self.monitor:
            self.monitor.dismiss_suggestion()
            self._refresh_task()
            self.correction_button.setFocus()
            self._status(tr("已保留当前主任务。"))

    def _mark_exclusions_dirty(self) -> None:
        self._exclusions_dirty = True

    def _sync_exclusions(self) -> None:
        if self.monitor and not self._exclusions_dirty:
            with QSignalBlocker(self.excluded_apps_input):
                self.excluded_apps_input.setPlainText("\n".join(self.monitor.excluded_apps))

    def _exclude_current_app(self) -> None:
        if self.monitor and self.monitor.snapshot:
            def exclude() -> str:
                app = self.monitor.snapshot.app_name
                self.monitor.exclude_current_app()
                if self._exclusions_dirty:
                    names = self.excluded_apps_input.toPlainText().splitlines()
                    if app not in names:
                        self.excluded_apps_input.appendPlainText(app)
                return tr("已排除 {0}，主任务继续保留。", app)
            self._perform(exclude)

    def _save_exclusions(self) -> None:
        if self.monitor:
            def save() -> str:
                names = [name.strip() for name in self.excluded_apps_input.toPlainText().splitlines() if name.strip()]
                self.monitor.set_excluded_apps(names)
                self._exclusions_dirty = False
                return tr("已保存应用排除列表。")
            self._perform(save)

    def _change_condition(self) -> None:
        def change() -> str:
            condition = Condition(self.condition_combo.currentData())
            self.session.set_condition(condition)
            self._analyzed_activity = None
            self._cancel_draft()
            self.resume_label.setText(tr(RESUME_HINT))
            return tr("已切换到 {0} 条件，开始新的运行记录。", condition.value)
        self._perform(change)
        self._sync_condition()

    def _sync_condition(self) -> None:
        with QSignalBlocker(self.condition_combo):
            self.condition_combo.setCurrentIndex(self.condition_combo.findData(self.session.condition.value))
        description = CONDITION_DESCRIPTIONS[self.session.condition]
        if self._uses_live_delegator and self.session.condition in (Condition.I, Condition.D):
            description = description.replace("离线委托", "公开检索委托")
        self.condition_description.setText(tr(description))

    def _analyze(self) -> None:
        def analyze() -> str:
            activity = self.activity_input.toPlainText().strip()
            if self.monitor:
                self.monitor.analyze_manual(activity)
            else:
                self.session.start_analysis(activity)
            self._analyzed_activity = activity
            self._manual_observation_key = self._observation_key()
            return tr("已提交补充活动，判断结果会显示在下方。")
        self._perform(analyze)

    def _add_detour(self, manual: bool = False) -> None:
        def add() -> str:
            activity = (self.monitor.activity_text if self.monitor and not manual
                        else self.activity_input.toPlainText())
            self.session.add_detour(activity)
            self._show_page(DETOURS)
            return tr("已暂存这条活动，可以继续主任务。")
        self._perform(add)

    def _refresh_detour_actions(self) -> None:
        enabled = self.session.memory_enabled and self.session.goal is not None
        selected = enabled and _selected_id(self.detour_list) is not None
        self.new_detour_button.setEnabled(enabled)
        self.edit_detour_button.setEnabled(selected)
        self.remove_detour_button.setEnabled(selected)

    def _edit_detour(self, new: bool = False) -> None:
        if not self.session.memory_enabled or self.session.goal is None:
            return
        item = None if new else next(
            (item for item in self.session.detours if item.id == _selected_id(self.detour_list)), None,
        )
        if not new and item is None:
            return
        self._editing_detour_id = item.id if item else None
        self._detour_editor_goal_id = self.session.goal.id
        self.detour_text_input.setPlainText(item.text if item else "")
        self.detour_url_input.setText(item.url if item else "")
        self.detour_purpose_input.setText(item.purpose if item else "")
        self.detour_error.clear()
        self.detour_editor.show()
        self.detour_text_input.setFocus()

    def _cancel_detour_edit(self) -> None:
        self.detour_editor.hide()
        self._editing_detour_id = None
        self._detour_editor_goal_id = None

    def _save_detour(self) -> None:
        def save() -> str:
            if self.session.goal is None or self._detour_editor_goal_id != self.session.goal.id:
                raise ValueError(tr("当前任务已改变，请重新打开支线编辑。"))
            values = (self.detour_text_input.toPlainText(), self.detour_url_input.text(),
                      self.detour_purpose_input.text())
            if self._editing_detour_id is None:
                item = self.session.add_detour(*values)
            else:
                item = self.session.update_detour(self._editing_detour_id, *values)
            self._cancel_detour_edit()
            self._refresh()
            _sync_rows(self.detour_list, self._detour_rows(), select=item.id)
            return tr("已保存支线笔记、链接和用途。")
        if not self._perform(save):
            self.detour_error.setText(self.status_label.text())

    def _remove_detour(self) -> None:
        if detour_id := _selected_id(self.detour_list):
            def remove() -> str:
                self.session.remove_detour(detour_id)
                self._cancel_detour_edit()
                return tr("已删除选中的支线。")
            self._perform(remove)

    def _detour_rows(self) -> list[tuple[str, str]]:
        return [(item.id, "\n".join(filter(None, (
            item.text, tr("链接：{0}", item.url) if item.url else "",
            tr("用途：{0}", item.purpose) if item.purpose else "",
        )))) for item in self.session.detours] if self.session.memory_enabled else []

    def _resume(self) -> None:
        def resume() -> None:
            self.session.resume()
            self._resume_requested_key = recovery_key(self.session.goal, self.session.progress)
        self._perform(resume)

    def _ignore_recovery(self) -> None:
        def ignore() -> str:
            self.session.ignore_recovery()
            self._resume_requested_key = None
            return tr("已忽略当前提示，任务与进度仍然保留。")
        self._perform(ignore)

    def _toggle_recovery(self) -> None:
        def toggle() -> str:
            self.session.set_recovery_paused(not self.session.recovery_paused)
            self._resume_requested_key = None
            return tr("已暂停恢复提示，可随时手动查看。") if self.session.recovery_paused else tr("已开启恢复提示。")
        self._perform(toggle)

    def _submit(self) -> None:
        if self._uses_live_delegator:
            self._formulate()
            return

        def submit() -> str:
            job = self.session.submit_delegation(self.question_input.text())
            self.question_input.clear()
            self._cancel_draft()
            self._show_page(DELEGATION)
            self._refresh_jobs(job.id)
            return tr("已提交离线演示委托，后台处理期间可以继续工作。")
        self._perform(submit)

    def _apply_draft(self, draft: DelegationDraft) -> None:
        self._draft = draft
        self._draft_goal_id = self.session.goal.id if self.session.goal else None
        self.draft_question_input.setText(draft.question)
        self.draft_scope_input.setText(draft.scope)
        self.draft_output_input.setText(draft.expected_output)
        if draft.needs_clarification:
            self.clarification_label.setText(tr("澄清建议：{0}", draft.clarification_question))
            self.clarification_input.clear()
            self.clarification_box.show()
        else:
            self.clarification_label.clear()
            self.clarification_input.clear()
            self.clarification_box.hide()
        self.draft_editor.show()

    def _formulate(self) -> None:
        self._perform(lambda: self._prepare_draft(self.question_input.text()))

    def _prepare_draft(self, question: str, clarification: str = "") -> str:
        goal = self.session.goal
        if not self.session.delegation_enabled or goal is None:
            raise ValueError(tr("请先设置主任务并在 I 或 D 条件下整理委托。"))
        if not question.strip():
            raise ValueError(tr("请输入需要委托的问题。"))
        if self._draft_future is not None:
            raise ValueError(tr("正在整理委托请求。"))
        self._show_page(DELEGATION)
        kwargs = {
            "goal_title": goal.title if not self._uses_live_delegator and self._draft_executor is None else "",
            "clarification_answer": clarification,
            "clarification_round": int(bool(clarification)),
        }
        if self._draft_executor is not None:
            self._draft_goal_id = goal.id
            self._draft_future = self._draft_executor.submit(self.formulator.draft, question, **kwargs)
            self.draft_editor.show()
            return tr("正在后台整理委托请求，可以继续处理主任务。")
        self._apply_draft(self.formulator.draft(question, **kwargs))
        return tr("已整理委托请求，可编辑后确认。")

    def _apply_clarification(self) -> None:
        def apply_clarify() -> str:
            if self._draft is None or not self._draft.needs_clarification:
                raise ValueError(tr("当前没有正在整理的委托请求。"))
            answer = self.clarification_input.text().strip()
            if not answer:
                raise ValueError(tr("请先填写澄清说明，或直接点击“确认并提交委托”。"))
            return self._prepare_draft(
                self.draft_question_input.text() or self._draft.raw_question,
                answer,
            )
        self._perform(apply_clarify)

    def _confirm_draft(self) -> None:
        def confirm() -> str:
            if self._draft is None or self._draft_future is not None:
                raise ValueError(tr("请等待委托请求整理完成。"))
            question = self.draft_question_input.text().strip()
            if not question:
                raise ValueError(tr("明确问题不能为空。"))
            draft = DelegationDraft(
                raw_question=self._draft.raw_question,
                question=question,
                scope=self.draft_scope_input.text().strip(),
                expected_output=self.draft_output_input.text().strip(),
                clarification_round=self._draft.clarification_round,
            )
            job = self.session.submit_delegation(draft.format_question())
            self.question_input.clear()
            self._cancel_draft()
            self._show_page(DELEGATION)
            self._refresh_jobs(job.id)
            return (
                tr("已确认并提交异步委托，后台正在检索公开来源，可继续处理主任务。")
                if self._uses_live_delegator
                else tr("已确认并提交离线演示委托，后台处理期间可以继续工作。")
            )
        self._perform(confirm)

    def _cancel_draft(self) -> None:
        if self._draft_future is not None:
            self._draft_future.cancel()
            self._draft_future = None
        self._draft = None
        self._draft_goal_id = None
        if hasattr(self, "draft_editor"):
            self.draft_question_input.clear()
            self.draft_scope_input.clear()
            self.draft_output_input.clear()
            self.clarification_input.clear()
            self.clarification_box.hide()
            self.draft_editor.hide()

    def _poll_draft(self) -> None:
        future = self._draft_future
        if future is None or not future.done():
            return
        goal = self.session.goal
        if goal is None or goal.id != self._draft_goal_id or not self.session.delegation_enabled:
            self._cancel_draft()
            self._refresh()
            return
        self._draft_future = None
        try:
            self._apply_draft(future.result())
        except UI_ERRORS as error:
            if self._draft is None:
                self._cancel_draft()
            self._status(str(error), error=True)
        else:
            self._status(tr("已整理委托请求，可编辑后确认。"))
        self._refresh()

    def _checkpoint(self) -> None:
        def checkpoint() -> str:
            count = self.session.checkpoint(self.checkpoint_label_input.text())
            self.checkpoint_label_input.clear()
            return tr("已记录检查点，交付了 {0} 项答案。", count)
        self._perform(checkpoint)

    def _reveal(self) -> None:
        if job_id := _selected_id(self.job_list):
            def reveal() -> str:
                self.session.reveal_job(job_id)
                return tr("已提前交付选中的答案。")
            self._perform(reveal)

    def _cancel(self) -> None:
        if job_id := _selected_id(self.job_list):
            self._perform(lambda: self.session.cancel_job(job_id))

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, tr("导出本次运行事件"), "intentaware-events.jsonl", "JSON Lines (*.jsonl)")
        if path:
            self._perform(lambda: tr("已导出 {0} 条运行事件。", self.session.export_events(path)))

    def _record_effective_edit(self) -> None:
        self._perform(self.session.record_effective_edit)

    def _refresh(self) -> None:
        memory, delegation = self.session.memory_enabled, self.session.delegation_enabled
        pending, has_goal = self.session.analysis_pending, self.session.goal is not None
        self._sync_condition()
        self._refresh_task()
        self._refresh_monitor()
        self._refresh_activity()
        self._refresh_classification()
        self.analyze_button.setEnabled(has_goal and not pending)
        self.activity_input.setEnabled(not pending)
        self.sample_button.setEnabled(not pending)
        active_jobs = any(job.status in (JobStatus.RUNNING, JobStatus.READY) for job in self.session.jobs)
        self.adopt_suggestion_button.setEnabled(not pending and not active_jobs)
        self.adopt_suggestion_button.setToolTip(tr("先完成或取消待交付的委托，再切换主任务。") if active_jobs else "")
        activity = self.monitor.activity_text if self.monitor else self.activity_input.toPlainText()
        self.detour_button.setEnabled(memory and has_goal and not pending and bool(activity.strip()))
        self.manual_detour_button.setEnabled(memory and has_goal and not pending and bool(self.activity_input.toPlainText().strip()))
        self.resume_button.setEnabled(memory and has_goal)
        self.ignore_recovery_button.setEnabled(memory and has_goal)
        self.pause_recovery_button.setEnabled(memory and has_goal)
        self.pause_recovery_button.setText(tr("开启恢复提示") if self.session.recovery_paused else tr("暂停恢复提示"))
        if self._draft_goal_id and (
            not delegation or not has_goal or self.session.goal.id != self._draft_goal_id
        ):
            self._cancel_draft()
        drafting = self._draft_future is not None
        can_draft = delegation and has_goal and not drafting
        self.question_input.setEnabled(can_draft)
        self.formulate_button.setEnabled(can_draft)
        self.submit_button.setEnabled(can_draft and not self._uses_live_delegator)
        for field in (self.draft_question_input, self.draft_scope_input, self.draft_output_input,
                      self.clarification_input, self.apply_clarification_button):
            field.setEnabled(can_draft)
        self.confirm_draft_button.setEnabled(can_draft and self._draft is not None)
        self.checkpoint_label_input.setEnabled(delegation and has_goal)
        self.checkpoint_button.setEnabled(delegation and has_goal)
        self.effective_edit_button.setEnabled(has_goal)
        self.detour_unavailable.setVisible(not memory)
        self.delegation_unavailable.setVisible(not delegation)

        detours = self.session.detours if memory else []
        self.detour_hint.setText(tr("已暂存 {0} 条活动，主任务与进度继续保留。", len(detours)) if detours else tr("把注意力先放回主任务，支线会留在这里。"))
        _sync_rows(self.detour_list, self._detour_rows())
        self.detour_list.setVisible(bool(detours))
        self.detour_empty.setVisible(not detours)
        if self._detour_editor_goal_id and (
            not memory or not has_goal or self.session.goal.id != self._detour_editor_goal_id
        ):
            self._cancel_detour_edit()
        self._refresh_detour_actions()
        key = recovery_key(self.session.goal, self.session.progress) if has_goal else None
        if key != self._resume_requested_key:
            self._resume_requested_key = None
        if memory and has_goal and self._resume_requested_key == key:
            self.resume_label.setText(recovery_text(self.session.goal, self.session.progress, detours))
        else:
            self.resume_label.setText(self.session.recovery_preview())
        self._refresh_jobs()
        self._refresh_events()

    def _refresh_events(self) -> None:
        _sync_rows(self.event_list, [
            (event.id, f"{datetime.fromisoformat(event.occurred_at):%H:%M:%S}     {event.condition.value}     "
                       f"{tr(EVENT_NAMES.get(event.name, event.name))}")
            for event in reversed(self.session.events)
        ])

    def _refresh_task(self) -> None:
        goal = self.session.goal
        _preview(self.task_title, goal.title if goal else tr("先回到你正在做的事"), 240)
        _preview(self.task_next_step, (goal.next_step or tr("点击“修正”，补充一个可以着手的下一步。")) if goal
                 else (tr("切回正在处理的应用，停留片刻；任务会在这里自动出现。") if self.monitor
                       else tr("点击“修正”设置主任务，再补充一次当前活动。")), 240)
        progress = self.session.progress.note if self.session.progress else ""
        _preview(self.progress_label, tr("已确认进度 · {0}", progress) if progress else tr("窗口变化不会自动改写已确认进度。"), 400)
        origin = self.monitor.goal_origin if self.monitor else "manual"
        text = {"automatic": tr("自动识别"), "manual": tr("手动确认"), "restored": tr("已恢复")}.get(origin, tr("待识别"))
        _badge(self.goal_origin_label, text if goal else tr("等待任务"), "accent" if goal else "")
        suggestion = self.monitor.switch_suggestion if self.monitor and not self._editing_goal else None
        self.suggestion_card.setVisible(suggestion is not None)
        if suggestion:
            _preview(self.suggestion_title, suggestion.title)
            _preview(self.suggestion_reason, tr("建议下一步 · {0}", suggestion.next_step), 200)

    def _refresh_monitor(self) -> None:
        if not self.monitor:
            _badge(self.monitor_status, tr("手动模式"))
            self.pause_button.hide()
            self.settings_monitor_status.setText(tr("当前以手动模式运行。重新启动正常模式后可自动识别。"))
            self.current_app_label.setText(tr("暂无前台应用线索"))
            self.exclude_current_button.setEnabled(False)
            self.excluded_apps_input.setEnabled(False)
            self.save_exclusions_button.setEnabled(False)
            return
        state = self.monitor.state
        states = {
            "starting": (tr("等待窗口线索"), ""), "watching": (tr("自动识别中"), "active"),
            "sampling": (tr("正在识别"), "active"), "paused": (tr("识别已暂停"), ""),
            "unavailable": (tr("识别暂不可用"), "warning"), "excluded": (tr("当前应用已排除"), ""),
            "idle": (tr("等待活动"), ""), "error": (tr("识别遇到问题"), "warning"),
        }
        text, tone = states.get(state, (tr("等待窗口线索"), ""))
        if self.demo and state in ("watching", "sampling"):
            text = tr("演示识别中")
        _badge(self.monitor_status, text, tone)
        self.monitor_status.setToolTip(self.monitor.message)
        self.pause_button.setText(tr("暂停识别") if self.monitor.enabled else tr("恢复识别"))
        self.pause_button.setIcon(icon("pause" if self.monitor.enabled else "play", size=16))
        self.settings_monitor_status.setText(self.monitor.message)
        snapshot = self.monitor.snapshot
        self.current_app_label.setText(tr("最近识别的应用：{0}", snapshot.app_name) if snapshot else tr("暂无可排除的应用线索"))
        self.exclude_current_button.setEnabled(snapshot is not None)
        self._sync_exclusions()

    def _refresh_activity(self) -> None:
        if not self.monitor:
            activity = self.activity_input.toPlainText().strip()
            _preview(self.activity_label, activity or tr("补充一次当前活动"))
            self.activity_source.setText(tr("手动输入 · LLM 分类") if self._uses_llm else tr("手动输入 · 本地分类"))
            self.window_title_label.hide()
            _badge(self.activity_state, tr("手动"))
            self.confidence_label.hide()
            self.recognition_reason.setText(tr("展开下方“手动补充活动”，描述你现在正在做什么。"))
            return
        snapshot, suggestion = self.monitor.snapshot, self.monitor.suggestion
        if snapshot and self.monitor.activity_text:
            activity_titles = {"开发": tr("代码编辑"), "写作": tr("文档编辑"), "阅读": tr("文献阅读"), "浏览": tr("网页浏览")}
            category = getattr(suggestion, "category", "未知") if suggestion else "未知"
            self.activity_label.setText(activity_titles.get(category, tr("正在使用工作窗口")))
            source = tr("示例窗口标题") if snapshot.source == "demo" else tr("前台窗口标题")
            if self._uses_llm:
                source = tr("{0} · 活动文本发送到模型端点", source)
            _preview(self.activity_source, f"{snapshot.app_name} · {source}")
            _preview(self.window_title_label, snapshot.window_title, 160)
            self.window_title_label.show()
            state_label = tr("最近一次") if self.monitor.state == "idle" else (tr("示例") if snapshot.source == "demo" else tr("已识别"))
            _badge(self.activity_state, state_label, "" if self.monitor.state == "idle" else "active")
            if suggestion:
                confidence = {"high": tr("把握较高"), "medium": tr("可供参考"), "low": tr("需要确认")}.get(suggestion.confidence, tr("需要确认"))
                _badge(self.confidence_label, confidence, "accent" if suggestion.confidence == "high" else "")
                self.confidence_label.show()
                _preview(self.recognition_reason, suggestion.reason, 160)
            else:
                self.confidence_label.hide()
                self.recognition_reason.setText(self.monitor.message)
        else:
            titles = {
                "paused": tr("自动识别已暂停"), "unavailable": tr("暂时无法读取窗口标题"),
                "excluded": tr("这个应用不参与识别"), "error": tr("还没有取得活动线索"),
            }
            self.activity_label.setText(titles.get(self.monitor.state, tr("等待你的工作窗口")))
            self.activity_source.setText(
                tr("应用名称与窗口标题 · 可随活动文本发送到模型端点") if self._uses_llm
                else tr("应用名称与窗口标题 · 仅在本机处理")
            )
            self.window_title_label.hide()
            self.confidence_label.hide()
            _badge(self.activity_state, tr("已暂停") if self.monitor.state == "paused" else tr("等待"))
            self.recognition_reason.setText(self.monitor.message or tr("回到正在处理的应用，停留片刻即可。"))

    def _observation_key(self) -> tuple[str, str] | None:
        snapshot = self.monitor.snapshot if self.monitor else None
        return (snapshot.app_name, snapshot.window_title) if snapshot else None

    def _refresh_classification(self) -> None:
        manual = self.activity_input.toPlainText().strip()
        manual_context = bool(manual and self._analyzed_activity == manual
                              and self._manual_observation_key == self._observation_key())
        activity = manual if manual_context or not self.monitor else self.monitor.activity_text
        result = self.session.classification
        classified_activity = getattr(self.session, "classification_activity", None) or self._analyzed_activity
        current = bool(activity and result and classified_activity == activity)
        self._distraction_prompt = (
            result if current and result.label == ActivityLabel.OPTIONAL_EXPLORATION else None
        )
        if self._distraction_prompt is None:
            self._recorded_distraction_prompt = None
        if self.session.analysis_pending and activity:
            title, text = tr("正在判断关联"), tr("正在对照当前主任务，稍后会在这里给出判断。")
        elif current:
            title = tr(CLASSIFICATIONS[result.label])
            source = tr("手动补充 · ") if manual_context and self.monitor else ""
            text = tr("{0}{1}\n\n建议：{2}", source, result.reason, result.suggested_next_step)
        elif self.monitor and not activity:
            title, text = tr("主任务继续保留"), tr("有新的活动线索时，再判断它与主任务的关系。")
        elif self.session.analysis_error:
            title, text = tr("暂时无法判断"), tr("{0}\n可以补充活动后重试。", self.session.analysis_error)
        else:
            title = tr("等待活动线索") if not activity else tr("还需要一些线索")
            text = tr(ANALYSIS_HINT) if self.monitor else tr("补充当前活动并分析后，会在这里给出判断。")
        self.classification_title.setText(title)
        _preview(self.classification_label, text, 1200)
        if self.session.analysis_pending and manual_context:
            manual_text = tr("正在判断补充的活动…")
        elif manual_context and result and classified_activity == manual:
            manual_text = tr(
                "{0} · {1}\n建议：{2}",
                tr(CLASSIFICATIONS[result.label]),
                result.reason,
                result.suggested_next_step,
            )
        elif self.session.analysis_error and self._analyzed_activity == manual:
            manual_text = tr("分析失败：{0}", self.session.analysis_error)
        else:
            manual_text = ""
        _preview(self.manual_classification_label, manual_text, 1200)
        self.manual_classification_label.setVisible(bool(manual_text))

    def _record_distraction_prompt(self) -> None:
        prompt = self._distraction_prompt
        if (
            prompt is not None and prompt is not self._recorded_distraction_prompt
            and not self.isMinimized() and self.classification_title.isVisible()
        ):
            self.session.record_event("distraction_prompted", {"source": "optional_exploration"})
            self._recorded_distraction_prompt = prompt
            self._refresh_events()

    def _refresh_jobs(self, select: str | None = None) -> None:
        jobs = self.session.jobs if self.session.delegation_enabled else []
        _sync_rows(self.job_list, [(job.id, f"{tr(JOB_STATES[job.status])}   {job.question}") for job in reversed(jobs)], select)
        self.job_list.setVisible(bool(jobs))
        self.job_empty.setVisible(not jobs)
        self._refresh_job_result()

    def _refresh_job_result(self) -> None:
        selected = _selected_id(self.job_list)
        job = next((job for job in self.session.jobs if job.id == selected), None)
        ready = job is not None and job.status == JobStatus.READY
        running = job is not None and job.status == JobStatus.RUNNING
        self.reveal_button.setEnabled(ready)
        self.cancel_button.setEnabled(ready or running)
        text = self._job_text(job)
        if self.job_result.toPlainText() != text:
            self.job_result.setPlainText(text)

    @staticmethod
    def _job_text(job: DelegationJob | None) -> str:
        if not job:
            return ""
        if job.status == JobStatus.DELIVERED and job.result:
            sources = "\n".join(
                tr("[来源 {0}] {1}\n{2}", index, source.title, source.url)
                for index, source in enumerate(job.result.sources, start=1)
            )
            return tr("{0}\n\n来源\n{1}", job.result.answer, sources) if sources else job.result.answer
        if job.status == JobStatus.READY:
            return tr("答案已就绪。到达检查点后交付，也可以提前查看。")
        if job.status == JobStatus.FAILED:
            return tr("委托失败：{0}", job.error or tr("未收到有效的答案。"))
        return tr(JOB_STATES[job.status])

    def _poll(self) -> None:
        try:
            changed = self.session.poll()
            if self.monitor:
                changed = self.monitor.poll() or changed
            if changed:
                self._refresh()
            self._record_distraction_prompt()
            self._poll_draft()
        except UI_ERRORS as error:
            self._status(str(error), error=True)

    def closeEvent(self, event: QCloseEvent) -> None:
        if not self._closed:
            self._closed = True
            self._timer.stop()
            self._cancel_draft()
            if self._draft_executor is not None:
                self._draft_executor.shutdown(wait=False, cancel_futures=True)
            try:
                if self.monitor:
                    self.monitor.close()
            except UI_ERRORS as error:
                self._status(str(error), error=True)
            try:
                self.session.close()
            except UI_ERRORS as error:
                self._status(str(error), error=True)
        super().closeEvent(event)
