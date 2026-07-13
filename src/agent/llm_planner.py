from __future__ import annotations

import json
from typing import Any

from src.agent.feasibility import FeasibilityResult, check_feasibility
from src.agent.planner import RulePlanner, TaskPlan
from src.data_resolver import SchemaSummary
from src.infra.llm_gateway import LLMGateway
from src.infra.llm_prompts import load_prompt
from src.task_spec import TaskSpec
from src.tools.catalog import catalog_as_prompt_text, export_tool_catalog
from src.tools.registry import ToolRegistry


def _as_args_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    return {}


ALLOWED_TOOLS_FALLBACK = {
    "setup_check",
    "data_profile",
    "clean_table",
    "plot_distributions",
    "eda_timeseries",
    "tokenize_jieba",
    "make_wordcloud",
    "llm_render_report",
    "render_report",
}


class LLMPlanner:
    """LLM 主路径规划器；失败时可降级到 RulePlanner。"""

    def __init__(
        self,
        gateway: LLMGateway,
        registry: ToolRegistry,
        *,
        allow_fallback: bool = True,
    ):
        self.gateway = gateway
        self.registry = registry
        self.allow_fallback = allow_fallback
        self.rule_planner = RulePlanner()
        self.last_source = "llm"

    def plan(self, task: TaskSpec, schema: SchemaSummary) -> tuple[TaskPlan, FeasibilityResult, str]:
        feas = check_feasibility(task, schema)
        catalog = export_tool_catalog(self.registry)
        allowed = {item["name"] for item in catalog} | ALLOWED_TOOLS_FALLBACK

        schema_payload = schema.to_dict()
        for t in schema_payload.get("tables", []):
            t["sample_rows"] = (t.get("sample_rows") or [])[:1]

        user_prompt = (
            f"TaskSpec:\n{json.dumps({'goal': task.goal, 'deliverables': task.deliverables, 'acceptance': task.acceptance, 'params': task.params}, ensure_ascii=False)}\n\n"
            f"Schema:\n{json.dumps(schema_payload, ensure_ascii=False)}\n\n"
            f"{catalog_as_prompt_text(catalog)}\n\n"
            "请输出 JSON：task_id, feasibility, notes, steps, acceptance_checks"
        )

        try:
            data = self.gateway.chat_json(
                [
                    {"role": "system", "content": load_prompt("system_planner.md")},
                    {"role": "user", "content": user_prompt},
                ],
                stage="planner",
            )
            plan = self._normalize_plan(data, task, allowed, feas)
            self.last_source = "llm"
            return plan, feas, "llm"
        except Exception as e:
            if not self.allow_fallback:
                raise RuntimeError(f"LLM 规划失败: {e}") from e
            plan, feas2 = self.rule_planner.plan(task, schema)
            # 规则规划器用 llm_render_report 替换 render_report
            for step in plan.steps:
                if step.get("tool") == "render_report":
                    step["tool"] = "llm_render_report"
            plan.notes = list(plan.notes) + [f"LLM 规划失败，已降级规则规划: {e}"]
            self.last_source = "rule_fallback"
            return plan, feas2, "rule_fallback"

    def _normalize_plan(
        self,
        data: dict[str, Any],
        task: TaskSpec,
        allowed: set[str],
        feas: FeasibilityResult,
    ) -> TaskPlan:
        steps_raw = data.get("steps") or []
        steps: list[dict[str, Any]] = []
        for i, s in enumerate(steps_raw):
            if not isinstance(s, dict):
                continue
            tool = str(s.get("tool") or "").strip()
            if tool == "render_report":
                tool = "llm_render_report"
            if tool not in allowed or not self.registry.has(tool):
                continue
            step_id = str(s.get("id") or f"step_{i}_{tool}")
            depends = s.get("depends_on") or []
            if not isinstance(depends, list):
                depends = []
            steps.append(
                {
                    "id": step_id,
                    "tool": tool,
                    "depends_on": [str(d) for d in depends],
                    "args": _as_args_dict(s.get("args")),
                }
            )

        if not steps:
            # 最小可用链路
            steps = [
                {"id": "profile", "tool": "data_profile", "depends_on": [], "args": {}},
                {"id": "clean", "tool": "clean_table", "depends_on": ["profile"], "args": {}},
                {"id": "plot", "tool": "plot_distributions", "depends_on": ["clean"], "args": {}},
                {"id": "report", "tool": "llm_render_report", "depends_on": ["plot"], "args": {}},
            ]

        # 确保有报告步骤
        if not any(s["tool"] == "llm_render_report" for s in steps):
            deps = [s["id"] for s in steps[-2:]] or [steps[-1]["id"]]
            steps.append(
                {"id": "report", "tool": "llm_render_report", "depends_on": deps, "args": {}}
            )

        # 确保开头有 profile（若无）
        if not any(s["tool"] == "data_profile" for s in steps):
            steps.insert(0, {"id": "profile", "tool": "data_profile", "depends_on": [], "args": {}})

        feasibility = str(data.get("feasibility") or feas.status)
        if feasibility not in {"feasible", "partial", "infeasible"}:
            feasibility = feas.status

        notes = [str(n) for n in (data.get("notes") or [])]
        notes.extend(feas.notes)

        acceptance = data.get("acceptance_checks") or []
        if not isinstance(acceptance, list):
            acceptance = []
        if not acceptance:
            acceptance = [{"type": "artifact_exists", "key": "report"}]
            if task.acceptance.get("need_clean_data") or "clean_data" in task.deliverables:
                acceptance.append({"type": "artifact_exists", "key": "clean_data"})

        return TaskPlan(
            task_id=str(data.get("task_id") or task.task_id),
            feasibility=feasibility,
            notes=notes,
            steps=steps,
            acceptance_checks=acceptance,
        )
