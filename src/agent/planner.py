from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.agent.feasibility import FeasibilityResult, check_feasibility
from src.data_resolver import SchemaSummary
from src.task_spec import TaskSpec


@dataclass
class TaskPlan:
    task_id: str
    feasibility: str
    notes: list[str] = field(default_factory=list)
    steps: list[dict[str, Any]] = field(default_factory=list)
    acceptance_checks: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "feasibility": self.feasibility,
            "notes": self.notes,
            "steps": self.steps,
            "acceptance_checks": self.acceptance_checks,
        }


def _wants(text: str, keywords: list[str]) -> bool:
    t = text.lower()
    return any(k.lower() in t or k in text for k in keywords)


def _joined_intent(task: TaskSpec) -> str:
    parts = [task.goal, *task.deliverables, *((task.report or {}).get("sections") or [])]
    return "\n".join(str(p) for p in parts)


class RulePlanner:
    """规则版 Planner：根据任务意图与可行性生成 DAG。"""

    def plan(self, task: TaskSpec, schema: SchemaSummary) -> tuple[TaskPlan, FeasibilityResult]:
        feas = check_feasibility(task, schema)
        intent = _joined_intent(task)
        steps: list[dict[str, Any]] = []

        def add(step_id: str, tool: str, depends_on: list[str] | None = None, **args: Any) -> None:
            steps.append(
                {
                    "id": step_id,
                    "tool": tool,
                    "depends_on": depends_on or [],
                    "args": args,
                }
            )

        add("setup", "setup_check")
        add("profile", "data_profile", depends_on=["setup"])

        need_clean = _wants(intent, ["清洗", "clean", "eda", "词云", "预测", "归因", "分布", "探索"]) or True
        if need_clean and feas.status != "infeasible":
            add("clean", "clean_table", depends_on=["profile"])

        if _wants(intent, ["eda", "分布", "探索", "图表", "可视化"]) or "clean_data" in (task.deliverables or []):
            if "clean" in [s["id"] for s in steps]:
                add("plot", "plot_distributions", depends_on=["clean"])

        if _wants(intent, ["时序", "趋势", "时间"]):
            if "clean" in [s["id"] for s in steps]:
                add("timeseries", "eda_timeseries", depends_on=["clean"])

        if _wants(intent, ["词云", "关键词", "分词", "文本挖掘"]):
            if "clean" in [s["id"] for s in steps]:
                add("tokenize", "tokenize_jieba", depends_on=["clean"])
                add("wordcloud", "make_wordcloud", depends_on=["tokenize"])

        # 默认总是出报告（LLM）
        last_ids = [s["id"] for s in steps]
        depends = [sid for sid in last_ids if sid not in {"setup"}][-3:] or ["profile"]
        add("report", "llm_render_report", depends_on=depends)

        acceptance: list[dict[str, Any]] = []
        acc = task.acceptance or {}
        if acc.get("figures_required"):
            acceptance.append({"type": "artifact_exists", "key_prefix": "score_distribution"})
        if "min_non_null_rate" in acc:
            acceptance.append(
                {
                    "type": "metric_gte",
                    "name": "non_null_rate_score",
                    "value": float(acc["min_non_null_rate"]),
                }
            )
        acceptance.append({"type": "artifact_exists", "key": "report"})
        if any("clean" in str(d).lower() or "清洗" in str(d) for d in (task.deliverables or ["清洗"])):
            acceptance.append({"type": "artifact_exists", "key": "clean_data"})

        plan = TaskPlan(
            task_id=task.task_id,
            feasibility=feas.status,
            notes=feas.notes,
            steps=steps,
            acceptance_checks=acceptance,
        )
        return plan, feas
