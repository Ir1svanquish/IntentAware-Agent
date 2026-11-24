"""生成 E 模块的样本候选池与数据表模板（一次性脚本，可重复运行覆盖）。

重要：本脚本生成的是**候选池**，不是已核验的金标准：
- expected_label 是场景的"设计意图"类别，供评审参考；
- baseline_prediction 是关键词基线的实际预测，用于暴露基线短板；
- 两者可能不一致，这正是需要两名评审独立判定的地方。

正式保留集必须由两名评审独立标注、分歧裁决并冻结后才能使用。
基线预测与预期不一致的样本尤其要重点核查。详见 README.md。

用法：
    python -m experiments.data.prepare_samples
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from ..baseline import classify_activity

DATA_DIR = Path(__file__).resolve().parent

# 候选上下文：goal, next_step, progress, activity, 设计意图标签, 构造说明。
# 四类各 15 条，共 60 条，与 Proposal 的保留样本数一致。
CONTEXT_CANDIDATES: tuple[tuple[str, str, str, str, str, str], ...] = (
    # 直接进展 15 条
    ("完成论文方法章", "写方法章提纲", "已读三篇文献", "整理方法章提纲并写入文档", "direct_progress", "直接产出提纲"),
    ("提交课程报告", "修改结论段", "正文已完成", "修改报告结论段的措辞", "direct_progress", "直接修改成果"),
    ("实现登录接口", "编写登录接口代码", "接口设计已定", "在 VS Code 中编写登录接口", "direct_progress", "编码产出"),
    ("准备毕业答辩", "制作第 3 页幻灯片", "大纲已定", "制作答辩第 3 页幻灯片", "direct_progress", "直接产出交付物"),
    ("完成读书报告", "整理第三章笔记", "前两章已写", "整理第三章的读书笔记", "direct_progress", "推进可量化任务"),
    ("完成论文实验", "运行主实验并保存结果", "环境已配置", "运行实验脚本并保存结果", "direct_progress", "执行下一步"),
    ("撰写文献综述", "写近三年研究综述正文", "文献已收集", "撰写文献综述正文", "direct_progress", "写作产出"),
    ("完成数据分析", "编写统计脚本", "数据已清洗", "编写 groupby 统计脚本", "direct_progress", "编码产出"),
    ("复习期末考试", "做完第三章习题", "前两章已复习", "做完第三章的习题", "direct_progress", "推进任务"),
    ("完成课程项目", "设计数据库表", "需求已确定", "设计项目的数据库表结构", "direct_progress", "直接产出设计"),
    ("写系统论文", "绘制系统架构图", "结构已构思", "绘制系统架构图", "direct_progress", "直接产出图表"),
    ("提交期刊文章", "修改审稿意见回复", "审稿意见已读", "逐条修改审稿意见回复", "direct_progress", "直接修改成果"),
    ("完成论文", "写摘要初稿", "结论已定稿", "撰写论文摘要初稿", "direct_progress", "写作产出"),
    ("完成测试标注", "标注第 21-30 条样本", "已标注 20 条", "标注第 21 到 30 条测试样本", "direct_progress", "推进可量化任务"),
    ("准备演讲稿", "写演讲稿开头", "主题已确定", "撰写演讲稿的开头段落", "direct_progress", "写作产出"),
    # 必要准备 15 条
    ("完成论文方法章", "写方法章提纲", "已读两篇", "前台窗口：Chrome｜Attention Is All You Need.pdf", "necessary_preparation", "读文献服务于方法章"),
    ("提交期刊文章", "写研究问题", "", "阅读第三章", "necessary_preparation", "同一活动在不同目标下是准备"),
    ("实现登录接口", "编写登录接口代码", "", "查阅 FastAPI 官方文档", "necessary_preparation", "查文档为编码准备"),
    ("准备毕业答辩", "制作第 3 页幻灯片", "", "浏览往届答辩视频找结构参考", "necessary_preparation", "收集结构参考"),
    ("完成论文", "修改结论段", "", "查找引用格式规范", "necessary_preparation", "规范准备"),
    ("复现基线实验", "配置训练环境", "", "安装 CUDA 与 PyTorch", "necessary_preparation", "环境准备"),
    ("撰写文献综述", "收集近三年文献", "", "在 arXiv 检索关键词", "necessary_preparation", "检索资料"),
    ("完成数据分析", "写统计脚本", "", "阅读 pandas groupby 教程", "necessary_preparation", "学习工具"),
    ("完成课程项目", "设计数据库表", "", "查看 SQLite 官方文档", "necessary_preparation", "查文档准备"),
    ("写系统论文", "画系统架构图", "", "收集同类系统的架构图参考", "necessary_preparation", "素材准备"),
    ("完成论文方法章", "写方法章提纲", "", "查找实验设计的统计方法", "necessary_preparation", "方法准备"),
    ("准备答辩", "制作幻灯片", "", "下载公司 logo 作为模板素材", "necessary_preparation", "素材准备"),
    ("完成报告", "写结论", "", "检索相关工作的对比数据", "necessary_preparation", "数据准备"),
    ("实现支付模块", "编写支付接口", "", "阅读支付网关的 API 文档", "necessary_preparation", "查文档准备"),
    ("复习数学", "做傅里叶变换习题", "", "看傅里叶变换的推导教程", "necessary_preparation", "学习准备"),
    # 可选探索 15 条
    ("完成论文", "写方法章节", "", "刷短视频找撰写论文的灵感", "optional_exploration", "休闲但沾边，不能判进展"),
    ("完成论文实验", "跑主实验", "", "逛 GitHub trending 看其他项目", "optional_exploration", "与主任务无关的探索"),
    ("复习期末考试", "做完第三章习题", "", "在购物网站比较显示器价格", "optional_exploration", "购物"),
    ("写完课程报告", "整理实验数据", "", "和朋友聊周末旅行", "optional_exploration", "闲聊"),
    ("提交期刊文章", "写研究问题", "", "刷微博热搜", "optional_exploration", "无关信息流"),
    ("实现登录接口", "编写登录接口代码", "", "看游戏直播", "optional_exploration", "娱乐"),
    ("准备毕业答辩", "制作第 3 页幻灯片", "", "刷小红书看答辩模板", "optional_exploration", "可能有用但非准备动作"),
    ("复现基线实验", "配置训练环境", "", "在视频网站看显卡评测", "optional_exploration", "硬件信息非当前任务"),
    ("撰写文献综述", "检索近三年文献", "", "浏览与课题无关的科技新闻", "optional_exploration", "信息浏览"),
    ("完成课程作业", "写第三题解答", "", "打游戏放松", "optional_exploration", "休息"),
    ("完成论文", "写文献综述", "", "刷朋友圈看同学动态", "optional_exploration", "社交信息流"),
    ("准备考试", "复习重点章节", "", "逛电商 App 看商品推荐", "optional_exploration", "购物推荐"),
    ("写报告", "整理数据", "", "看了一段搞笑视频", "optional_exploration", "娱乐放松"),
    ("做项目", "调试接口", "", "在论坛闲逛看帖", "optional_exploration", "无关浏览"),
    ("学习英语", "背单词", "", "刷短视频看宠物", "optional_exploration", "完全无关的娱乐"),
    # 不确定 15 条
    ("完成论文方法章", "整理三篇文献并写提纲", "", "打开了一个窗口", "unclear", "没有任何有效线索"),
    ("完成论文", "写方法章节", "", "前台窗口：Code｜未命名-1", "unclear", "通用标题无法推断"),
    ("提交课程报告", "修改结论段", "", "在浏览器里看东西", "unclear", "描述过泛"),
    ("实现登录接口", "编写登录接口代码", "", "切换到了另一个应用", "unclear", "没有活动内容"),
    ("准备毕业答辩", "制作第 3 页幻灯片", "", "前台窗口：Finder｜Documents", "unclear", "只有文件管理器"),
    ("完成论文实验", "跑主实验", "", "处理一些事情", "unclear", "无法判断"),
    ("撰写文献综述", "检索近三年文献", "", "打开了设置页面", "unclear", "系统页面"),
    ("完成数据分析", "写统计脚本", "", "浏览网页", "unclear", "信息不足"),
    ("复习期末考试", "做完第三章习题", "", "在文档里写了一些内容", "unclear", "未说明与目标关系"),
    ("完成课程项目", "设计数据库表", "", "前台窗口：Microsoft Edge｜新标签页", "unclear", "空白页"),
    ("写论文", "写第二章", "", "打开了一个应用", "unclear", "无有效线索"),
    ("做作业", "解第二题", "", "查看了桌面", "unclear", "无活动内容"),
    ("准备面试", "整理项目经历", "", "切换窗口", "unclear", "无活动内容"),
    ("写报告", "画流程图", "", "前台窗口：未知应用", "unclear", "无标题信息"),
    ("完成任务", "提交作业", "", "打开了某页面", "unclear", "描述过泛"),
)

# 候选委托请求：支线问题，用于评估异步委托的答案质量与引用支持。
DELEGATION_CANDIDATES: tuple[tuple[str, str, str], ...] = (
    ("d-01", "Macro-F1 和 micro-F1 在多分类里有什么区别？", "分类评估"),
    ("d-02", "Python 的 argparse 怎么设置必填参数？", "编程"),
    ("d-03", "什么是组内实验设计的 carryover effect？", "实验设计"),
    ("d-04", "SQLite 的 WAL 模式适合什么场景？", "数据库"),
    ("d-05", "pandas 里 groupby 和 agg 的区别是什么？", "数据分析"),
    ("d-06", "论文里 'we propose' 和 'we present' 语气有区别吗？", "学术写作"),
    ("d-07", "PySide6 的信号槽在主线程和子线程有什么区别？", "GUI 编程"),
    ("d-08", "如何计算 95% 置信区间？", "统计"),
    ("d-09", "什么是 p 值的常见误用？", "统计"),
    ("d-10", "LLM 的 temperature 参数怎么影响输出？", "模型"),
    ("d-11", "为什么需要 train/dev/test 三层划分？", "机器学习"),
    ("d-12", "Markdown 表格怎么对齐？", "写作工具"),
    ("d-13", "git rebase 和 merge 该怎么选？", "工具"),
    ("d-14", "什么是数据泄露（data leakage）？", "机器学习"),
    ("d-15", "如何给实验报告写 limitation 部分？", "学术写作"),
    ("d-16", "Python 的虚拟环境 venv 和 conda 有何不同？", "编程"),
    ("d-17", "什么是 blinding（盲法）在用户研究中的作用？", "实验设计"),
    ("d-18", "GPT 类的 token 计费是怎么算的？", "模型"),
    ("d-19", "如何检测时间序列中的异常值？", "数据分析"),
    ("d-20", "Likert 量表的数据该用哪种统计检验？", "统计"),
    ("d-21", "什么叫过拟合，怎么判断？", "机器学习"),
    ("d-22", "表单的 CSRF 防护原理是什么？", "安全"),
    ("d-23", "什么是 prompt injection？", "安全"),
    ("d-24", "如何写可复现的实验记录？", "研究方法"),
    ("d-25", "PDF 里的引用怎么导出成 BibTeX？", "工具"),
    ("d-26", "交叉验证的 k 值怎么选？", "机器学习"),
    ("d-27", "为什么随机种子要固定？", "机器学习"),
    ("d-28", "什么是效应量（effect size）？", "统计"),
    ("d-29", "如何设计一个好的用户调研问题？", "实验设计"),
    ("d-30", "Windows 上怎么查看前台窗口标题？", "技术"),
    ("d-31", "JSONL 和 JSON 有什么区别？", "数据格式"),
    ("d-32", "什么是注意力机制的核心思想？", "模型"),
    ("d-33", "如何避免实验中的要求特征（demand characteristics）？", "实验设计"),
    ("d-34", "正则表达式里 ?: 是什么意思？", "编程"),
    ("d-35", "如何评估答案是否有引用支持？", "评估"),
    ("d-36", "用户研究中的知情同意应包含哪些内容？", "伦理"),
    ("d-37", "如何做远程用户测试的招募？", "实验设计"),
    ("d-38", "F1 的宏平均和加权平均有什么区别？", "评估"),
    ("d-39", "Python 里 dataclass 和 namedtuple 怎么选？", "编程"),
    ("d-40", "如何给代码写清晰的 docstring？", "编程"),
)


def build_contexts() -> list[dict]:
    rows: list[dict] = []
    for index, (goal, step, progress, activity, expected, note) in enumerate(CONTEXT_CANDIDATES, start=1):
        prediction = classify_activity(activity, goal, step, progress)
        rows.append({
            "id": f"holdout-{index:03d}",
            "goal_title": goal,
            "goal_next_step": step,
            "progress": progress,
            "activity": activity,
            "expected_label": expected,  # 设计意图，待评审确认
            "baseline_prediction": prediction.label.value,  # 基线实际预测
            "note": note,
            "review_status": "pending",  # 两名评审核查后改为 approved
        })
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def write_annotation_sheet(path: Path, rows: list[dict]) -> None:
    """空白标注表：评审独立填写，避免预填标签造成锚定偏差。"""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "id", "goal_title", "goal_next_step", "progress", "activity",
            "reviewer_a_label", "reviewer_b_label", "final_label",
            "disagreement_reason", "reviewer_a", "reviewer_b", "date",
        ])
        for row in rows:
            writer.writerow([
                row["id"], row["goal_title"], row["goal_next_step"],
                row["progress"], row["activity"], "", "", "", "", "", "", "",
            ])


def write_delegation_sheet(path: Path) -> None:
    """委托请求候选池 + 空白评估列。"""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([
            "id", "question", "topic", "sources_count", "source_1_url",
            "source_2_url", "citation_supported", "answer_quality_1_5",
            "unresolved_points", "evaluator",
        ])
        for job_id, question, topic in DELEGATION_CANDIDATES:
            writer.writerow([job_id, question, topic, "", "", "", "", "", "", ""])


def main() -> None:
    contexts = build_contexts()
    write_jsonl(DATA_DIR / "holdout_contexts.jsonl", contexts)
    write_jsonl(
        DATA_DIR / "holdout_delegations.jsonl",
        [{"id": job_id, "question": question, "topic": topic}
         for job_id, question, topic in DELEGATION_CANDIDATES],
    )
    write_annotation_sheet(DATA_DIR / "annotation_sheet.csv", contexts)
    write_delegation_sheet(DATA_DIR / "delegation_eval_sheet.csv")
    disagreements = sum(
        1 for row in contexts if row["expected_label"] != row["baseline_prediction"]
    )
    print(f"已生成 {len(contexts)} 条上下文候选、{len(DELEGATION_CANDIDATES)} 条委托候选。")
    print(f"其中 {disagreements} 条基线与设计意图不一致，需评审重点核查。")
    print("注意：标签为候选草案，review_status=pending，需两名评审核查后才能用于正式评估。")


if __name__ == "__main__":
    main()
