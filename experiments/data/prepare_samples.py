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
# 重要：本候选池的活动描述刻意避开 B 模块 #13 的 40 条开发样本，
# 以保证隔离。新增场景时务必用 isolate 子命令复查。
CONTEXT_CANDIDATES: tuple[tuple[str, str, str, str, str, str], ...] = (
    # 直接进展 15 条
    ("完成论文方法章", "写方法章提纲", "已列好小节", "在文档里补写实验设置小节", "direct_progress", "直接产出提纲内容"),
    ("提交课程报告", "修改结论段", "正文已完成", "调整结论段最后一句话的措辞", "direct_progress", "直接修改成果"),
    ("实现登录接口", "编写登录接口代码", "接口设计已定", "在编辑器里补上密码校验分支", "direct_progress", "编码产出"),
    ("准备毕业答辩", "制作第 3 页幻灯片", "大纲已定", "给第三页幻灯片插入流程图", "direct_progress", "直接产出交付物"),
    ("完成读书报告", "整理第三章笔记", "前两章已写", "把第三章要点誊进读书笔记", "direct_progress", "推进可量化任务"),
    ("完成论文实验", "运行主实验并保存结果", "环境已配置", "执行训练命令并把日志另存", "direct_progress", "执行下一步并保存"),
    ("撰写文献综述", "写近三年研究综述正文", "文献已收集", "补写 2024 年相关工作的段落", "direct_progress", "写作产出"),
    ("完成数据分析", "编写统计脚本", "数据已清洗", "给统计脚本加上显著性检验", "direct_progress", "编码产出"),
    ("复习期末考试", "做完第三章习题", "前两章已复习", "写出第三章第五题的解答", "direct_progress", "推进任务"),
    ("完成课程项目", "设计数据库表", "需求已确定", "在建模工具里画出用户表字段", "direct_progress", "直接产出设计"),
    ("写系统论文", "绘制系统架构图", "结构已构思", "用绘图工具画出模块调用关系", "direct_progress", "直接产出图表"),
    ("提交期刊文章", "修改审稿意见回复", "审稿意见已读", "把第二条审稿意见回复改成英文", "direct_progress", "直接修改成果"),
    ("完成论文", "写摘要初稿", "结论已定稿", "在摘要里补上主要实验数字", "direct_progress", "写作产出"),
    ("完成测试标注", "复核已标注样本", "已标注 20 条", "复核并修正前十条标注的标签", "direct_progress", "推进可量化任务"),
    ("准备演讲稿", "写演讲稿开头", "主题已确定", "写出演讲稿开场的两段话", "direct_progress", "写作产出"),
    # 必要准备 15 条
    ("完成论文方法章", "写方法章提纲", "已读两篇", "前台窗口：Chrome｜Transformer 原文 PDF", "necessary_preparation", "读文献服务于方法章"),
    ("提交期刊文章", "写研究问题", "", "重读导师批注过的那段引言", "necessary_preparation", "为写研究问题做准备"),
    ("实现登录接口", "编写登录接口代码", "", "打开 HTTP 状态码对照表查 401 含义", "necessary_preparation", "查资料为编码准备"),
    ("准备毕业答辩", "制作第 3 页幻灯片", "", "收藏了几份学长答辩的排版", "necessary_preparation", "收集结构参考"),
    ("完成论文", "修改结论段", "", "翻看期刊的格式模板说明", "necessary_preparation", "规范准备"),
    ("复现基线实验", "配置训练环境", "", "对照 README 检查显卡驱动版本", "necessary_preparation", "环境准备"),
    ("撰写文献综述", "收集近三年文献", "", "在知网用关键词筛出 2025 年论文", "necessary_preparation", "检索资料"),
    ("完成数据分析", "写统计脚本", "", "翻看 numpy 广播机制的说明页", "necessary_preparation", "学习工具"),
    ("完成课程项目", "设计数据库表", "", "搜索外键约束的写法示例", "necessary_preparation", "查文档准备"),
    ("写系统论文", "画系统架构图", "", "找了几张分层架构的参考图", "necessary_preparation", "素材准备"),
    ("完成论文方法章", "写方法章提纲", "", "查了一下宏平均 F1 的定义", "necessary_preparation", "方法准备"),
    ("准备答辩", "制作幻灯片", "", "下载学校统一的答辩模板", "necessary_preparation", "素材准备"),
    ("完成报告", "写结论", "", "查了同类研究的对比数值", "necessary_preparation", "数据准备"),
    ("实现支付模块", "编写支付接口", "", "在沙箱文档里找测试卡号", "necessary_preparation", "查文档准备"),
    ("复习数学", "做傅里叶变换习题", "", "重看欧拉公式的推导视频", "necessary_preparation", "学习准备"),
    # 可选探索 15 条
    ("完成论文", "写方法章节", "", "点开短视频刷了一会宠物合集", "optional_exploration", "休闲娱乐"),
    ("完成论文实验", "跑主实验", "", "翻看行业资讯 App 的推荐流", "optional_exploration", "与主任务无关的信息浏览"),
    ("复习期末考试", "做完第三章习题", "", "在二手平台浏览相机价格", "optional_exploration", "购物"),
    ("写完课程报告", "整理实验数据", "", "和室友聊晚上的聚餐安排", "optional_exploration", "闲聊"),
    ("提交期刊文章", "写研究问题", "", "刷了一下本地同城动态", "optional_exploration", "无关信息流"),
    ("实现登录接口", "编写登录接口代码", "", "看了半小时电竞比赛直播", "optional_exploration", "娱乐"),
    ("准备毕业答辩", "制作第 3 页幻灯片", "", "在图片社区翻答辩穿搭帖子", "optional_exploration", "可能有用但非准备动作"),
    ("复现基线实验", "配置训练环境", "", "看了一篇手机测评文章", "optional_exploration", "硬件信息非当前任务"),
    ("撰写文献综述", "检索近三年文献", "", "浏览体育新闻首页", "optional_exploration", "无关信息浏览"),
    ("完成课程作业", "写第三题解答", "", "打开小游戏玩了两局", "optional_exploration", "休息"),
    ("完成论文", "写文献综述", "", "翻看朋友圈的图片", "optional_exploration", "社交信息流"),
    ("准备考试", "复习重点章节", "", "在购物 App 看运动鞋", "optional_exploration", "购物推荐"),
    ("写报告", "整理数据", "", "看了一段脱口秀片段", "optional_exploration", "娱乐放松"),
    ("做项目", "调试接口", "", "在兴趣论坛读了几个闲聊帖", "optional_exploration", "无关浏览"),
    ("学习英语", "背单词", "", "刷了一段猫咪短视频", "optional_exploration", "完全无关的娱乐"),
    # 不确定 15 条
    ("完成论文方法章", "整理三篇文献并写提纲", "", "双击了一个桌面图标", "unclear", "没有任何有效线索"),
    ("完成论文", "写方法章节", "", "前台窗口：Code｜README.md", "unclear", "通用文档标题无法推断"),
    ("提交课程报告", "修改结论段", "", "在某个窗口里停留了一会儿", "unclear", "描述过泛"),
    ("实现登录接口", "编写登录接口代码", "", "打开了一个未命名的程序", "unclear", "没有活动内容"),
    ("准备毕业答辩", "制作第 3 页幻灯片", "", "前台窗口：Finder｜下载", "unclear", "只有文件管理器"),
    ("完成论文实验", "跑主实验", "", "稍微处理了一点事务", "unclear", "无法判断"),
    ("撰写文献综述", "检索近三年文献", "", "打开了一个偏好设置窗口", "unclear", "系统页面"),
    ("完成数据分析", "写统计脚本", "", "看了一会儿屏幕", "unclear", "信息不足"),
    ("复习期末考试", "做完第三章习题", "", "在编辑器里敲了几个字符", "unclear", "未说明内容与目标关系"),
    ("完成课程项目", "设计数据库表", "", "前台窗口：浏览器｜空白标签", "unclear", "空白页"),
    ("写论文", "写第二章", "", "启动了一个未知程序", "unclear", "无有效线索"),
    ("做作业", "解第二题", "", "看了一眼任务栏", "unclear", "无活动内容"),
    ("准备面试", "整理项目经历", "", "窗口标题只有一串数字", "unclear", "标题无语义"),
    ("写报告", "画流程图", "", "前台窗口：未识别应用", "unclear", "无标题信息"),
    ("完成任务", "提交作业", "", "打开了一个文件夹", "unclear", "描述过泛"),
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
