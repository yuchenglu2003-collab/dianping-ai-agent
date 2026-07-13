from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.data_resolver import SchemaSummary
from src.task_spec import TaskSpec


# deliverable 关键词 -> 需要的标准字段
DELIVERABLE_REQUIREMENTS: dict[str, list[str]] = {
    "clean_data": [],
    "清洗": [],
    "report": [],
    "figures": [],
    "eda": [],
    "分布图": [],
    "timeseries": [],
    "时序": [],
    "wordcloud": ["content"],
    "词云": ["content"],
    "关键词": ["content"],
    "attribution": ["score"],
    "归因": ["score"],
    "rating_model": ["score", "content"],
    "评分预测": ["score", "content"],
    "模型": ["score", "content"],
    "漏斗": ["event_type", "user_id"],
    "funnel": ["event_type", "user_id"],
    "rfm": ["user_id"],
    "销量预测": ["sales_qty"],
    "sales_forecast": ["sales_qty"],
    "异常": [],
}


@dataclass
class FeasibilityResult:
    status: str  # feasible | partial | infeasible
    missing: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    enabled_deliverables: list[str] = field(default_factory=list)
    disabled_deliverables: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "missing": self.missing,
            "notes": self.notes,
            "enabled_deliverables": self.enabled_deliverables,
            "disabled_deliverables": self.disabled_deliverables,
        }


def available_columns(schema: SchemaSummary) -> set[str]:
    cols: set[str] = set()
    for t in schema.tables:
        cols.update(t.mapped_columns.values())
        cols.update(t.columns)
    return {c.lower() for c in cols}


def check_feasibility(task: TaskSpec, schema: SchemaSummary) -> FeasibilityResult:
    cols = available_columns(schema)
    missing_all: list[str] = []
    notes: list[str] = []
    enabled: list[str] = []
    disabled: list[str] = []

    deliverables = task.deliverables or [task.goal]
    for d in deliverables:
        reqs: list[str] = []
        low = d.lower()
        for key, need in DELIVERABLE_REQUIREMENTS.items():
            if key.lower() in low or key in d:
                reqs.extend(need)
        reqs = sorted(set(reqs))
        miss = [r for r in reqs if r.lower() not in cols and r not in cols]
        if miss:
            disabled.append(d)
            missing_all.extend(miss)
            notes.append(f"产出「{d}」缺少字段: {miss}")
        else:
            enabled.append(d)

    missing_all = sorted(set(missing_all))
    if not deliverables:
        status = "feasible"
    elif not disabled:
        status = "feasible"
    elif enabled:
        status = "partial"
    else:
        status = "infeasible"

    if not schema.tables:
        status = "infeasible"
        notes.append("未探查到任何数据表")

    return FeasibilityResult(
        status=status,
        missing=missing_all,
        notes=notes,
        enabled_deliverables=enabled,
        disabled_deliverables=disabled,
    )
