from __future__ import annotations

from src.task_loader import _slugify
from src.task_spec import TaskSpec


def infer_deliverables_from_text(text: str) -> list[str]:
    """从自然语言任务描述推断期望产出。"""
    deliverables: list[str] = []
    if any(k in text for k in ["清洗", "干净", "缺失", "异常", "去重", "clean"]):
        deliverables.append("clean_data")
    if any(k in text for k in ["EDA", "eda", "探索", "分布", "可视化", "图表", "时序", "趋势", "分析"]):
        deliverables.append("EDA分布图与时序图")
    if any(k in text for k in ["词云", "关键词", "分词", "高频词", "文本"]):
        deliverables.append("词云与关键词结论")
    if any(k in text for k in ["归因", "好评", "口味", "服务", "环境"]):
        deliverables.append("归因分析报告")
    if any(k in text for k in ["预测", "模型", "分类", "评分预测"]):
        deliverables.append("评分预测模型")
    if any(k in text for k in ["漏斗", "PV", "UV", "CTR", "CVR"]):
        deliverables.append("流量漏斗看板")
    if any(k in text for k in ["RFM", "用户分层", "用户价值"]):
        deliverables.append("RFM用户分层")
    if any(k in text for k in ["销量", "预测销量", "异常检测"]):
        deliverables.append("销量预测报告")
    if not deliverables:
        deliverables = ["clean_data", "EDA分布图与时序图"]
    return deliverables


def build_task_from_text(goal: str) -> TaskSpec:
    goal = goal.strip()
    if not goal:
        raise ValueError("请填写任务要求")

    task_id = _slugify(goal[:40] or "analysis_task")
    deliverables = infer_deliverables_from_text(goal)

    raw_text = "\n".join(
        [
            f"# 任务：{goal[:60]}",
            "",
            "## 目标",
            goal,
            "",
            "## 期望产出",
            *[f"- {d}" for d in deliverables],
        ]
    )

    return TaskSpec(
        task_id=task_id,
        goal=goal,
        deliverables=deliverables,
        acceptance={"figures_required": True},
        params={"drop_duplicates": True, "positive_threshold": 4},
        report={"title": "数据分析报告"},
        raw_path=None,
        raw_text=raw_text,
    )
