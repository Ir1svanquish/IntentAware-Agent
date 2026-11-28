import pytest

from intentaware.activity.models import ActivitySnapshot
from intentaware.contracts import ActivityContext, ActivityLabel, Goal
from intentaware.nlp.local import LocalActivityClassifier, LocalTaskRecognizer


@pytest.mark.parametrize("app,title,subject,category,confidence", [
    ("Code.exe", "main.py - IntentAware-AutoTask - Visual Studio Code", "IntentAware-AutoTask", "开发", "high"),
    ("Code", "● 观察.py — 自动任务 — Visual Studio Code", "自动任务", "开发", "high"),
    ("Code.exe", "parser.py - Visual Studio Code", "parser.py", "开发", "medium"),
    ("WINWORD.EXE", "研究计划.docx - Word", "研究计划", "写作", "high"),
    ("Microsoft Word", "Annual report - Microsoft Word", "Annual report", "写作", "high"),
    ("AcroRd32.exe", "Attention Is All You Need.pdf - Adobe Acrobat Reader", "Attention Is All You Need", "阅读", "high"),
    ("evince", "实验方法.pdf", "实验方法", "阅读", "high"),
    ("chrome.exe", "Qt for Python documentation - Google Chrome", "Qt for Python documentation", "浏览", "medium"),
    ("msedge.exe", "PySide6 信号与槽 - Microsoft Edge", "PySide6 信号与槽", "浏览", "medium"),
])
def test_bilingual_window_titles_produce_editable_specific_suggestions(app, title, subject, category, confidence):
    snapshot = ActivitySnapshot(app, title)
    suggestion = LocalTaskRecognizer().infer(snapshot)
    assert subject in suggestion.title
    assert suggestion.next_step
    assert suggestion.category == category
    assert suggestion.confidence == confidence
    assert suggestion.source_key == snapshot.key
    assert suggestion.activity.startswith("前台窗口：")
    assert title in suggestion.activity
    assert "标题" in suggestion.reason


@pytest.mark.parametrize("app,title", [
    ("Code.exe", "Visual Studio Code"), ("Code.exe", "Welcome - Visual Studio Code"),
    ("Code.exe", "Untitled-1 - Visual Studio Code"), ("WINWORD.EXE", "Document1 - Word"),
    ("WINWORD.EXE", "文档1 - Word"), ("chrome.exe", "新标签页 - Google Chrome"),
    ("firefox", "New Tab — Mozilla Firefox"), ("unknown-app", "Window"),
    ("terminal", "bash"), ("chrome.exe", ""),
    ("chrome.exe", "Google - Google Chrome"),
    ("evince", "Document Viewer"),
])
def test_sparse_titles_do_not_invent_initial_task(app, title):
    result = LocalTaskRecognizer().infer(ActivitySnapshot(app, title))
    assert result.confidence == "low"
    assert result.title == ""
    assert result.next_step == ""


def test_recognizer_does_not_echo_private_title():
    result = LocalTaskRecognizer().infer(ActivitySnapshot("chrome.exe", "Secret page - Incognito"))
    assert result.confidence == "low"
    assert result.title == result.next_step == result.activity == ""
    assert "Secret" not in result.reason


def classify_window(goal, app, title):
    activity = LocalTaskRecognizer().infer(ActivitySnapshot(app, title)).activity
    return LocalActivityClassifier().classify(ActivityContext(goal, activity))


def test_related_editor_is_a_possible_main_task_context_not_confirmed_progress():
    result = classify_window(Goal("完善 IntentAware-AutoTask", "实现窗口识别"), "Code.exe", "observer.py - IntentAware-AutoTask - Visual Studio Code")
    assert result.label is ActivityLabel.DIRECT_PROGRESS
    assert "未验证" in result.reason


def test_unrelated_editor_does_not_automatically_count_as_progress():
    result = classify_window(Goal("完成论文", "整理实验结果"), "Code.exe", "main.py - weather-service - Visual Studio Code")
    assert result.label is ActivityLabel.UNCLEAR


def test_generic_editor_words_do_not_create_false_goal_overlap():
    result = classify_window(Goal("继续开发论文项目", "编写论文分析脚本"), "Code.exe", "main.py - other-project - Visual Studio Code")
    assert result.label is ActivityLabel.UNCLEAR


def test_related_document_is_recognized_with_chinese_subject_overlap():
    result = classify_window(Goal("撰写睡眠质量论文", "整理实验结果"), "WINWORD.EXE", "睡眠质量.docx - Word")
    assert result.label is ActivityLabel.DIRECT_PROGRESS


def test_related_browser_reference_is_preparation():
    result = classify_window(Goal("实现 PySide6 窗口", "接入前台识别"), "chrome.exe", "PySide6 signals tutorial - Google Chrome")
    assert result.label is ActivityLabel.NECESSARY_PREPARATION


def test_browser_brand_in_goal_does_not_make_unrelated_page_relevant():
    result = classify_window(Goal("开发 Chrome 插件", "实现侧边栏"), "chrome.exe", "Weather forecast - Google Chrome")
    assert result.label is ActivityLabel.UNCLEAR


def test_specific_reading_next_step_can_make_pdf_main_task():
    result = classify_window(Goal("理解实验方法", "阅读实验方法"), "evince", "实验方法.pdf")
    assert result.label is ActivityLabel.DIRECT_PROGRESS


def test_obvious_unrelated_entertainment_is_only_a_possible_detour():
    result = classify_window(Goal("完成论文", "整理实验结果"), "chrome.exe", "搞笑合集 - 抖音 - Google Chrome")
    assert result.label is ActivityLabel.OPTIONAL_EXPLORATION


def test_entertainment_site_related_to_research_goal_is_not_blanket_blocked():
    result = classify_window(Goal("调研抖音推荐界面", "收集界面样本"), "chrome.exe", "抖音推荐界面介绍 - Google Chrome")
    assert result.label is ActivityLabel.NECESSARY_PREPARATION


@pytest.mark.parametrize("activity,label", [
    ("正在撰写论文正文", ActivityLabel.DIRECT_PROGRESS),
    ("查阅论文相关文献", ActivityLabel.NECESSARY_PREPARATION),
    ("刷短视频找撰写论文的灵感", ActivityLabel.OPTIONAL_EXPLORATION),
    ("打开了一个窗口", ActivityLabel.UNCLEAR),
    ("", ActivityLabel.UNCLEAR),
])
def test_local_classifier_preserves_manual_keyword_semantics(activity, label):
    result = LocalActivityClassifier().classify(ActivityContext(Goal("完成论文", "整理实验结果"), activity))
    assert result.label is label
    assert "演示" not in result.reason
    assert "整理实验结果" in result.suggested_next_step


def test_manual_next_step_still_takes_precedence_over_preparation_keyword():
    result = LocalActivityClassifier().classify(ActivityContext(Goal("完成报告", "阅读第三章"), "阅读第三章"))
    assert result.label is ActivityLabel.DIRECT_PROGRESS


@pytest.mark.parametrize(("activity", "label"), [
    ("I am writing a birthday card for a friend.", ActivityLabel.UNCLEAR),
    ("I am reading restaurant menus to choose where to eat.", ActivityLabel.UNCLEAR),
    ("I'm not writing the report. I'm waiting for feedback.", ActivityLabel.UNCLEAR),
    ("I was not able to draft the methods section.", ActivityLabel.UNCLEAR),
    ("I am writing a birthday card. The methods section is on hold.", ActivityLabel.UNCLEAR),
    ("I am revising the methods section based on reviewer comments.", ActivityLabel.DIRECT_PROGRESS),
    ("I am not writing the introduction, but I am editing the methods section.", ActivityLabel.DIRECT_PROGRESS),
    ("I am reading the codebook for the methods section.", ActivityLabel.NECESSARY_PREPARATION),
    ("Draft the methods section.", ActivityLabel.DIRECT_PROGRESS),
    ("As a side question, look up travel prices.", ActivityLabel.OPTIONAL_EXPLORATION),
])
def test_manual_english_classification_uses_affirmative_goal_evidence(activity, label):
    goal = Goal("Complete the research report", "Draft the methods section")
    result = LocalActivityClassifier().classify(ActivityContext(goal, activity))
    assert result.label is label
