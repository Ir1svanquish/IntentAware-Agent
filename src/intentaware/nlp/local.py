"""Explainable local rules for app/title task hints and goal-aware activity.

Window metadata identifies a possible work context, never completed work. The
separate observation prefix keeps that weaker evidence distinct from explicit
activity descriptions supplied by the person using the workbench.
"""

from dataclasses import dataclass
import ntpath
import re

from intentaware.localization import english, tr
from intentaware.activity.models import ActivitySnapshot, TaskSuggestion
from intentaware.activity.observer import MAX_APP_CHARS, MAX_TITLE_CHARS, is_private_snapshot
from intentaware.contracts import ActivityContext, ActivityLabel, Classification
from intentaware.nlp.demo import DemoClassifier
from intentaware.nlp.text import topic_tokens


# 对外公开：其他分类实现需要识别“窗口观察”与“用户描述”两种来源。
OBSERVATION_PREFIX = "前台窗口："
_DELIMITER = "｜"
_SEPARATOR = re.compile(r"\s+[-—–|]\s+")
_SUFFIX = re.compile(
    r"\s+[-—–|]\s+(?:Visual Studio Code|Code - Insiders|VSCodium|Cursor|"
    r"Microsoft Word|Word|WPS Office|LibreOffice Writer|Adobe Acrobat(?: Reader)?|"
    r"SumatraPDF|Document Viewer|Evince|Okular|Google Chrome|Chromium|"
    r"Mozilla Firefox|Firefox|Microsoft Edge|Brave|Opera|Vivaldi)(?:\s*\[[^]]*\])?$",
    re.I,
)
_GENERIC = re.compile(
    r"^(?:untitled(?:[- ]?\d+)?|document\d*|new tab|new window|welcome|settings|"
    r"home|start page|blank page|visual studio code|google chrome|microsoft edge|"
    r"mozilla firefox|word|about:blank|google|bing|baidu|百度|document viewer|"
    r"adobe acrobat(?: reader)?|evince|okular|sumatrapdf|文档\d*|未命名\d*|无标题[- ]?\d*|"
    r"新标签页|新建标签页|新建窗口|欢迎|设置|主页|首页|空白页)$", re.I,
)
_FILE_EXTENSION = re.compile(r"\.[a-z][a-z0-9]{0,9}$", re.I)
_DOC_EXTENSION = re.compile(r"\.(?:docx?|odt|rtf)$", re.I)
_LEISURE = re.compile(r"刷短视频|搞笑|抖音|淘宝|京东|购物|打游戏|玩游戏|\b(?:netflix|youtube shorts|funny cats|shopping)\b", re.I)


def observation_payload(activity: str) -> str | None:
    for prefix in (OBSERVATION_PREFIX, english(OBSERVATION_PREFIX).rstrip()):
        if activity.startswith(prefix):
            return activity[len(prefix):].lstrip()
    return None


@dataclass(frozen=True)
class _WindowDetails:
    category: str = "未知"
    subject: str = ""
    filename: str = ""
    confidence: str = "low"


def _meaningful(value: str) -> bool:
    value = value.strip()
    return len(value) >= 2 and not _GENERIC.fullmatch(value) and bool(re.search(r"[\w\u3400-\u9fff]", value))


def _details(snapshot: ActivitySnapshot) -> _WindowDetails:
    app = ntpath.basename(snapshot.app_name).casefold().removesuffix(".exe")
    title = snapshot.window_title.strip()[:MAX_TITLE_CHARS]
    clean = _SUFFIX.sub("", title).strip().lstrip("●•* ")
    parts = [part.strip() for part in _SEPARATOR.split(clean) if part.strip()]
    first = parts[0] if parts else ""
    if not _meaningful(first):
        return _WindowDetails()
    if re.search(r"\.pdf(?:$|\s)", first, re.I) or app in {"acrord32", "acrobat", "sumatrapdf", "evince", "okular", "zathura", "org.gnome.evince"}:
        subject = re.sub(r"\.pdf$", "", first, flags=re.I).strip()
        return _WindowDetails("阅读", subject, first, "high") if _meaningful(subject) else _WindowDetails()
    if app in {"code", "code-oss", "code-insiders", "visual studio code", "vscodium", "cursor"}:
        filename = first if _FILE_EXTENSION.search(first) else ""
        project = re.sub(r"\s*\[(?:SSH|WSL|Dev Container)[^]]*\]", "", parts[-1], flags=re.I).strip()
        if len(parts) > 1 and _meaningful(project):
            return _WindowDetails("开发", project, filename, "high" if filename else "medium")
        return _WindowDetails("开发", first, filename, "medium")
    if app in {"winword", "word", "microsoft word", "wps", "libreoffice writer", "soffice"} or _DOC_EXTENSION.search(first):
        subject = _DOC_EXTENSION.sub("", first).strip()
        return _WindowDetails("写作", subject, first, "high") if _meaningful(subject) else _WindowDetails()
    if app in {"chrome", "google-chrome", "google chrome", "chromium", "chromium-browser", "msedge", "microsoft edge", "firefox", "firefox-esr", "brave", "brave-browser", "opera", "vivaldi"}:
        return _WindowDetails("浏览", first, confidence="medium")
    return _WindowDetails()


class LocalTaskRecognizer:
    def infer(self, snapshot: ActivitySnapshot) -> TaskSuggestion:
        if is_private_snapshot(snapshot):
            return TaskSuggestion("", "", "", "low", tr("隐私窗口已排除。"), snapshot.key)
        activity = (
            f"{tr(OBSERVATION_PREFIX)}{snapshot.app_name[:MAX_APP_CHARS]}"
            f"{_DELIMITER}{snapshot.window_title[:MAX_TITLE_CHARS]}"
        )
        details = _details(snapshot)
        subject = details.subject[:160]
        if details.category == "浏览" and _LEISURE.search(snapshot.window_title):
            return TaskSuggestion(
                "", "", activity, "low", tr("标题包含休闲或购物线索，暂时仅记录为当前活动。"),
                snapshot.key, details.category,
            )
        if details.confidence == "low":
            return TaskSuggestion(
                "", "", activity, "low", tr("本地规则：应用和窗口标题中的任务线索不足，等待更明确的窗口或你的补充。"), snapshot.key,
            )
        if details.category == "开发":
            title_template = "继续开发「{0}」"
            next_step = tr("确认 {0} 的修改目标，并继续处理", details.filename or subject)
        elif details.category == "写作":
            title_template = "撰写「{0}」"
            next_step = tr("确认「{0}」要完善的段落，并继续编辑", subject)
        elif details.category == "阅读":
            title_template = "阅读「{0}」"
            next_step = tr("阅读「{0}」并记下当前需要的要点", subject)
        else:
            title_template = "查阅「{0}」"
            next_step = tr("明确当前页面要解决的问题，并记录有用的信息")
        return TaskSuggestion(
            tr(title_template, subject), next_step, activity, details.confidence,
            tr("本地规则：根据前台应用与窗口标题识别为{0}上下文；未读取内容，任务可随时修正。", tr(details.category)),
            snapshot.key, details.category,
            # Match the titles used as keys by pre-localization databases.
            identity_title=title_template.format(subject),
        )


def _related(goal_text: str, details: _WindowDetails) -> bool:
    if details.filename and len(details.filename) >= 4 and details.filename.casefold() in goal_text.casefold():
        return True
    return bool(topic_tokens(goal_text) & topic_tokens(f"{details.subject} {details.filename}"))


class LocalActivityClassifier:
    def classify(self, context: ActivityContext) -> Classification:
        activity = context.activity.strip()
        payload = observation_payload(activity)
        if payload is None:
            # Keep established explicit, user-entered activity semantics. Those
            # assertions are stronger evidence than merely opening an editor.
            result = DemoClassifier().classify(context)
            return Classification(result.label, result.reason.replace(tr("规则演示："), tr("本地规则："), 1), result.suggested_next_step)
        fields = payload.split(_DELIMITER, 1)
        snapshot = ActivitySnapshot(fields[0], fields[1] if len(fields) > 1 else "")
        details = _details(snapshot)
        next_step = context.goal.next_step.strip()
        suggestion = tr("对照当前下一步：{0}", next_step) if next_step else tr("补充一个具体的下一步，帮助判断活动与目标的关系。")
        related = _related(f"{context.goal.title} {next_step}", details)
        if related and details.confidence != "low":
            if details.category in {"开发", "写作"}:
                return Classification(
                    ActivityLabel.DIRECT_PROGRESS,
                    tr("本地规则：窗口中的项目或文件与当前目标相符，可能正在处理主线；未验证修改或实际进度。"),
                    suggestion,
                )
            if re.search(r"阅读|审阅|通读|\b(?:read|reading|review)\b", next_step, re.I) and _related(next_step, details):
                return Classification(
                    ActivityLabel.DIRECT_PROGRESS,
                    tr("本地规则：窗口主题与设定的阅读下一步相符；未验证阅读进度。"), suggestion,
                )
            return Classification(
                ActivityLabel.NECESSARY_PREPARATION,
                tr("本地规则：页面或文档主题与当前目标相符，可能是在查阅所需资料；未验证具体用途。"), suggestion,
            )
        if details.category == "浏览" and _LEISURE.search(snapshot.window_title):
            return Classification(
                ActivityLabel.OPTIONAL_EXPLORATION,
                tr("本地规则：标题含休闲或购物线索，未找到与当前目标的明确关联，可能是可稍后处理的支线。"), suggestion,
            )
        return Classification(
            ActivityLabel.UNCLEAR,
            tr("本地规则：仅凭当前应用与窗口标题，无法确定这项活动如何帮助主目标；你可以补充或修正。"), suggestion,
        )
