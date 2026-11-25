"""活动分类的关键词基线，用于与 LLM 分类器对照。

基线只使用活动描述、目标标题、下一步和已确认进度的字面关键词，
不调用模型、不联网。它的作用是提供一个可复现的下界，而不是替代
B 模块的分类器。样本格式与 ``intentaware.nlp.evaluate`` 一致：

    {"id": "holdout-001", "goal_title": "...", "goal_next_step": "...",
     "progress": "...", "activity": "...", "expected_label": "..."}

输出可直接喂给 ``experiments/metrics.py`` 计算 Macro-F1 与误提醒率。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from .metrics import DIRECT_LABELS, DISTRACTION_LABELS, VALID_LABELS, UNCLEAR

# 规则按顺序匹配，命中第一条即停止。休闲线索优先，避免"刷短视频找灵感"
# 因含有目标关键词而被误判成直接进展。
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("optional_exploration", (
        "刷短视频", "刷微博", "打游戏", "玩游戏", "看直播", "购物", "逛淘宝",
        "闲聊", "聊周末", "小红书", "无关", "娱乐", "放松", "刷视频",
    )),
    ("necessary_preparation", (
        "查阅", "阅读", "查找", "检索", "查资料", "收集资料", "收集", "教程",
        "官方文档", "看文档", "预习", "准备", "找参考", "找例子", "找结构参考",
        "安装", "配置环境", "找灵感", "查引用", "搜索",
    )),
    ("direct_progress", (
        "撰写", "写正文", "写方法", "写摘要", "写结论", "修改", "编写", "实现",
        "整理", "标注", "制作", "绘制", "画图", "运行实验", "提交", "做完",
        "保存结果", "写登录", "设计数据库",
    )),
)

# 信息量过低、无法判断的描述。命中即返回 unclear，防止关键词误触发。
_LOW_INFORMATION = (
    "打开了一个窗口", "未命名", "新标签页", "切换到了另一个应用",
    "处理一些事情", "浏览网页", "看东西", "打开了设置", "在文档里写了一些内容",
    "前台窗口：finder", "新建文档",
)


@dataclass(frozen=True)
class Prediction:
    """与 B 模块 Classification 兼容的最小结果（label.value / reason）。"""

    label: Any
    reason: str


class _Label:
    """只提供 .value 的轻量标签，避免基线依赖 intentaware.contracts。"""

    def __init__(self, value: str) -> None:
        self.value = value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Label) and other.value == self.value

    def __repr__(self) -> str:  # pragma: no cover - 仅调试展示
        return f"_Label({self.value!r})"


def classify_activity(
    activity: str,
    goal_title: str = "",
    next_step: str = "",
    progress: str = "",
) -> Prediction:
    """用关键词规则给单条活动分类，返回带理由的预测。"""
    text = activity.strip().casefold()
    step = next_step.strip().casefold()

    for phrase in _LOW_INFORMATION:
        if phrase in text:
            return Prediction(
                _Label(UNCLEAR),
                f"基线：描述“{activity.strip()}”信息量不足，无法判断与任务的关系。",
            )

    for label, keywords in _RULES:
        for keyword in keywords:
            if keyword in text:
                return Prediction(
                    _Label(label),
                    f"基线：命中关键词“{keyword}”，判为{label}。",
                )

    # 下一步与活动高度重合时，视为直接进展；这一步放在规则之后，
    # 避免"刷短视频找撰写论文的灵感"这类休闲活动被下一步关键词带偏。
    if step and (step in text or text in step):
        return Prediction(
            _Label("direct_progress"),
            f"基线：活动与下一步“{next_step.strip()}”一致。",
        )

    return Prediction(
        _Label(UNCLEAR),
        "基线：活动描述未命中任何规则，信息不足以分类。",
    )


def load_samples(path: str | Path) -> list[dict]:
    """读取 JSONL 样本，空行跳过，坏行报错（与 B 模块行为一致）。"""
    rows: list[dict] = []
    for number, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            raise ValueError(f"样本第 {number} 行不是合法 JSON。") from None
        if not isinstance(row, dict):
            raise ValueError(f"样本第 {number} 行不是 JSON 对象。")
        missing = [key for key in ("id", "activity", "expected_label") if key not in row]
        if missing:
            raise ValueError(f"样本第 {number} 行缺少字段：{', '.join(missing)}。")
        if row["expected_label"] not in VALID_LABELS:
            raise ValueError(
                f"样本第 {number} 行的 expected_label 非法：{row['expected_label']!r}。"
            )
        rows.append(row)
    if not rows:
        raise ValueError("样本文件为空。")
    return rows


def run_baseline(samples: list[Mapping[str, Any]]) -> list[dict]:
    """对样本逐条跑基线，返回带 expected/predicted 的明细行。"""
    details: list[dict] = []
    for sample in samples:
        prediction = classify_activity(
            activity=str(sample["activity"]),
            goal_title=str(sample.get("goal_title", "")),
            next_step=str(sample.get("goal_next_step", "")),
            progress=str(sample.get("progress", "")),
        )
        details.append({
            "id": sample["id"],
            "expected": sample["expected_label"],
            "predicted": prediction.label.value,
            "reason": prediction.reason,
            "activity": str(sample["activity"]),
            "note": str(sample.get("note", "")),
        })
    return details


# 供 B 模块 evaluate.py 直接注入的适配器：实现 classify(context) 接口。
class KeywordBaselineClassifier:
    """实现 ``Classifier`` 协议的关键词基线，可传给 ``nlp.evaluate``。"""

    def classify(self, context: Any) -> Prediction:
        goal = getattr(context, "goal", None)
        return classify_activity(
            activity=str(getattr(context, "activity", "")),
            goal_title=str(getattr(goal, "title", "")),
            next_step=str(getattr(goal, "next_step", "")),
            progress=str(getattr(context, "progress", "")),
        )


__all__ = [
    "Prediction", "KeywordBaselineClassifier", "classify_activity",
    "load_samples", "run_baseline", "DIRECT_LABELS", "DISTRACTION_LABELS",
]
