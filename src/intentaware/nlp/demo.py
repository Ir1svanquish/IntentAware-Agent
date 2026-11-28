"""Demonstrate four-way activity classification with keyword rules."""

import re

from intentaware.localization import tr
from intentaware.contracts import ActivityContext, ActivityLabel, Classification
from intentaware.nlp.text import topic_tokens


# 活动描述未匹配下一步时，按顺序使用第一个匹配的规则。
_RULES = (
    (
        ActivityLabel.OPTIONAL_EXPLORATION,
        ("刷短视频", "刷微博", "闲聊", "购物", "打游戏", "玩游戏", "顺便", "无关",
         "as a side question", "as a side activity", "unrelated", "shopping", "playing a game",
         "scrolling short videos"),
        "可能是可以稍后处理的支线",
        "先记下支线，然后回到下一步",
    ),
    (
        ActivityLabel.NECESSARY_PREPARATION,
        ("查阅", "阅读", "查找", "教程", "收集资料", "查资料", "准备", "预习",
         "read", "reading", "review", "reviewing", "look up", "research", "tutorial", "gather"),
        "看起来是在为任务查找资料或做准备",
        "找够当前所需的信息后，回到下一步",
    ),
    (
        ActivityLabel.DIRECT_PROGRESS,
        ("撰写", "编写", "写正文", "修改", "整理", "绘制", "实现", "运行实验", "提交",
         "write", "writing", "edit", "editing", "draft", "drafting", "revise", "revising",
         "implement", "implementing", "run the tests", "submit"),
        "看起来是在执行任务或更新成果",
        "继续当前工作，并对照下一步",
    ),
)


_CLAUSE_BREAK = re.compile(r"[!?;\n]+|\.(?=\s|$)|\bbut\b")
_ENGLISH_NEGATION = re.compile(r"\b(?:not(?!\s+only\b)|never|cannot|no longer|[a-z]+n['’]t)\b")
_HAN = re.compile(r"[\u3400-\u9fff]")
_GENERIC_ACTIVITY_TERMS = {
    "chapter", "chapters", "section", "sections", "draft", "drafting", "revise", "revising",
    "gather", "reviewing", "submit", "submission", "your", "our", "their",
}


def _english_phrase(phrase: str, clause: str) -> bool:
    return bool(re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", clause))


class DemoClassifier:
    def classify(self, context: ActivityContext) -> Classification:
        activity = context.activity.strip().casefold()
        next_step = context.goal.next_step.strip()
        affirmative = [clause for clause in _CLAUSE_BREAK.split(activity) if not _ENGLISH_NEGATION.search(clause)]
        step = next_step.casefold()
        if _HAN.search(step):
            matches_next_step = step in activity
        else:
            step = step.rstrip(".!?;")
            matches_next_step = bool(step) and any(_english_phrase(step, clause) for clause in affirmative)
        if matches_next_step:
            return Classification(
                ActivityLabel.DIRECT_PROGRESS,
                tr("规则演示：活动描述包含你为当前目标设定的下一步。"),
                tr("继续执行下一步：{0}", next_step),
            )

        goal_topics = topic_tokens(f"{context.goal.title} {next_step}") - _GENERIC_ACTIVITY_TERMS
        related_clauses = [clause for clause in affirmative if goal_topics & topic_tokens(clause)]
        for label, keywords, explanation, suggestion in _RULES:
            clauses = affirmative if label is ActivityLabel.OPTIONAL_EXPLORATION else related_clauses
            matched = next(
                (keyword for keyword in keywords if (
                    any(_english_phrase(keyword, clause) for clause in clauses)
                    if keyword.isascii() else keyword in activity
                )),
                None,
            )
            if matched:
                return Classification(
                    label,
                    tr("规则演示：检测到“{0}”，{1}。", matched, tr(explanation)),
                    tr("{0}：{1}", tr(suggestion), next_step),
                )

        return Classification(
            ActivityLabel.UNCLEAR,
            tr("规则演示：描述中的信息不足以判断活动如何帮助“{0}”。", context.goal.title),
            tr("补充活动会带来的具体结果，然后对照下一步：{0}", next_step),
        )
