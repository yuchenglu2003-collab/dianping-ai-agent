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
        kinds = {t.table_kind for t in schema.tables}

        def add(step_id: str, tool: str, depends_on: list[str] | None = None, **args: Any) -> None:
            steps.append({"id": step_id, "tool": tool, "depends_on": depends_on or [], "args": args})

        add("profile", "data_profile")
        add("clean", "clean_table", depends_on=["profile"])

        # Week1 EDA / 词云
        if _wants(intent, ["eda", "分布", "探索", "图表", "可视化", "清洗", "周报"]) or "reviews" in kinds:
            if _wants(intent, ["eda", "分布", "探索", "图表", "可视化", "清洗", "周报", "第一周"]):
                add("plot", "plot_distributions", depends_on=["clean"])
        if _wants(intent, ["时序", "趋势", "时间"]):
            add("timeseries", "eda_timeseries", depends_on=["clean"])
        if _wants(intent, ["词云", "关键词", "分词", "文本挖掘"]):
            add("tokenize", "tokenize_jieba", depends_on=["clean"])
            add("wordcloud", "make_wordcloud", depends_on=["tokenize"])

        # Week2 归因 / 模型
        if _wants(intent, ["归因", "口味", "服务", "环境", "好评"]):
            add("attribution", "attribution_aspects", depends_on=["clean"])
        if _wants(intent, ["评分预测", "模型", "tfidf", "随机森林", "贝叶斯", "xgb", "调优"]):
            add("rating_model", "rating_predict", depends_on=["clean"])

        # Week3 漏斗 / RFM
        if _wants(intent, ["漏斗", "pv", "uv", "ctr", "cvr", "gmv", "dau", "arpu", "流量"]) or "behavior" in kinds:
            if _wants(intent, ["漏斗", "pv", "uv", "ctr", "cvr", "gmv", "流量", "第三周"]):
                add("funnel", "funnel_metrics", depends_on=["clean"])
        if _wants(intent, ["rfm", "用户分层", "用户价值", "挽留"]):
            add("rfm", "rfm_segment", depends_on=["clean"])

        # Week4 销量
        if _wants(intent, ["销量预测", "异常", "门店销量", "第四周"]) or "sales" in kinds:
            if _wants(intent, ["销量", "预测", "异常", "第四周", "gmv"]):
                add("sales", "sales_forecast", depends_on=["clean"])

        # 若几乎没匹配到分析步，按表类型兜底
        analytic_ids = {s["id"] for s in steps} - {"profile", "clean"}
        if not analytic_ids:
            if "behavior" in kinds:
                add("funnel", "funnel_metrics", depends_on=["clean"])
                add("rfm", "rfm_segment", depends_on=["clean"])
            elif "sales" in kinds:
                add("plot", "plot_distributions", depends_on=["clean"])
                add("sales", "sales_forecast", depends_on=["clean"])
            else:
                add("plot", "plot_distributions", depends_on=["clean"])
                add("timeseries", "eda_timeseries", depends_on=["clean"])

        last_ids = [s["id"] for s in steps]
        depends = last_ids[-3:] or ["clean"]
        add("report", "llm_render_report", depends_on=depends)

        acceptance = [{"type": "artifact_exists", "key": "report"}]
        if any("clean" in str(d).lower() or "清洗" in str(d) for d in (task.deliverables or ["清洗"])):
            acceptance.append({"type": "artifact_exists", "key": "clean_data"})

        plan = TaskPlan(
            task_id=task.task_id,
            feasibility=feas.status if feas.status != "infeasible" else "partial",
            notes=feas.notes,
            steps=steps,
            acceptance_checks=acceptance,
        )
        return plan, feas
