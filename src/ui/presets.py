from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskPreset:
    id: str
    label: str
    goal: str
    deliverables: list[str] = field(default_factory=list)
    acceptance: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    report_title: str = ""


PRESETS: list[TaskPreset] = [
    TaskPreset(
        id="eda_wordcloud",
        label="评论清洗 + EDA + 词云",
        goal="对评论数据做清洗与探索性分析，输出分布图、时序趋势、关键词词云与初步结论",
        deliverables=["clean_data", "EDA分布图与时序图", "词云与关键词结论"],
        acceptance={"min_non_null_rate": 0.95, "figures_required": True},
        report_title="评论数据探索性分析报告",
    ),
    TaskPreset(
        id="eda_only",
        label="仅数据清洗与 EDA",
        goal="清洗数据并输出评分/门店分布图与时序趋势",
        deliverables=["clean_data", "EDA分布图与时序图"],
        acceptance={"min_non_null_rate": 0.9, "figures_required": True},
        report_title="数据清洗与探索性分析报告",
    ),
    TaskPreset(
        id="wordcloud_only",
        label="文本挖掘（分词 + 词云）",
        goal="对评论文本分词，提取高频词并生成词云图",
        deliverables=["词云与关键词结论"],
        acceptance={"figures_required": True},
        report_title="评论关键词分析报告",
    ),
    TaskPreset(
        id="custom",
        label="自定义任务",
        goal="",
        deliverables=[],
        acceptance={},
        report_title="数据分析任务报告",
    ),
]


def get_preset(preset_id: str) -> TaskPreset:
    for p in PRESETS:
        if p.id == preset_id:
            return p
    return PRESETS[-1]
