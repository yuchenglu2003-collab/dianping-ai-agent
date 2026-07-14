from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable

from src.agent.executor import Executor
from src.agent.planner import TaskPlan
from src.agent.step_labels import STEP_LABELS
from src.data_resolver import SchemaSummary
from src.infra.llm_gateway import LLMGateway
from src.infra.llm_prompts import load_prompt
from src.run_context import RunContext
from src.task_spec import TaskSpec
from src.tools.catalog import catalog_as_prompt_text, export_tool_catalog
from src.tools.registry import ToolRegistry

ProgressCallback = Callable[[float, str], None]

# ReAct 中可调用的工具（跳过纯检查类）
REACT_TOOLS = {
    "clean_table",
    "data_profile",
    "plot_distributions",
    "eda_timeseries",
    "tokenize_jieba",
    "make_wordcloud",
    "attribution_aspects",
    "rating_predict",
    "funnel_metrics",
    "rfm_segment",
    "sales_forecast",
    "llm_render_report",
}


@dataclass
class ReActTraceStep:
    index: int
    thought: str
    action: str
    action_input: dict[str, Any]
    observation: str
    success: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "thought": self.thought,
            "action": self.action,
            "action_input": self.action_input,
            "observation": self.observation,
            "success": self.success,
        }


@dataclass
class ReActResult:
    finished: bool
    steps: list[ReActTraceStep] = field(default_factory=list)
    plan_steps: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "finished": self.finished,
            "final_answer": self.final_answer,
            "error": self.error,
            "steps": [s.to_dict() for s in self.steps],
            "plan_steps": self.plan_steps,
        }

    def as_task_plan(self, task: TaskSpec) -> TaskPlan:
        acceptance: list[dict[str, Any]] = [{"type": "artifact_exists", "key": "report"}]
        if any(ctx_key in str(task.deliverables).lower() for ctx_key in ("clean", "清洗")):
            acceptance.append({"type": "artifact_exists", "key": "clean_data"})
        notes = [self.final_answer] if self.final_answer else []
        if self.error:
            notes.append(self.error)
        return TaskPlan(
            task_id=task.task_id,
            feasibility="feasible" if self.finished and not self.error else "partial",
            notes=notes,
            steps=self.plan_steps,
            acceptance_checks=acceptance,
        )


def _truncate(text: str, limit: int = 1200) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 20] + "\n…(truncated)"


def _schema_brief(schema: SchemaSummary) -> dict[str, Any]:
    table = schema.primary()
    if table is None:
        return {}
    return {
        "path": table.path,
        "rows": table.rows,
        "columns": table.columns[:40],
        "mapped_columns": table.mapped_columns,
        "table_kind": table.table_kind,
        "sample_rows": (table.sample_rows or [])[:2],
    }


class ReActAgent:
    """经典 ReAct：Thought → Action → Observation 循环，直到 finish。"""

    def __init__(
        self,
        gateway: LLMGateway,
        registry: ToolRegistry,
        executor: Executor,
        *,
        max_steps: int = 12,
    ):
        self.gateway = gateway
        self.registry = registry
        self.executor = executor
        self.max_steps = max_steps

    def run(
        self,
        ctx: RunContext,
        task: TaskSpec,
        schema: SchemaSummary,
        *,
        on_progress: ProgressCallback | None = None,
        progress_start: float = 0.2,
        progress_end: float = 0.92,
    ) -> ReActResult:
        catalog = [c for c in export_tool_catalog(self.registry) if c["name"] in REACT_TOOLS]
        allowed = {c["name"] for c in catalog}
        system = load_prompt("system_react.md")
        history: list[dict[str, str]] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    "开始 ReAct 任务。\n"
                    f"用户目标：{task.goal or task.raw_text}\n"
                    f"交付物：{task.deliverables}\n"
                    f"数据概况：{json.dumps(_schema_brief(schema), ensure_ascii=False)}\n"
                    f"{catalog_as_prompt_text(catalog)}\n"
                    "请输出第一轮 JSON（thought/action/action_input）。"
                ),
            },
        ]

        result = ReActResult(finished=False)
        fail_counts: dict[str, int] = {}

        for i in range(1, self.max_steps + 1):
            pct = progress_start + (progress_end - progress_start) * ((i - 1) / self.max_steps)
            if on_progress:
                on_progress(pct, f"ReAct 第 {i}/{self.max_steps} 轮：思考中...")

            try:
                decision = self.gateway.chat_json(history, stage=f"react_step_{i}")
            except Exception as e:
                result.error = f"ReAct LLM 调用失败: {e}"
                break

            thought = str(decision.get("thought") or "")
            action = str(decision.get("action") or "").strip()
            action_input = decision.get("action_input") if isinstance(decision.get("action_input"), dict) else {}
            final_answer = str(decision.get("final_answer") or "")

            assistant_raw = json.dumps(decision, ensure_ascii=False)
            history.append({"role": "assistant", "content": assistant_raw})

            if action in {"finish", "done", "stop", "complete"}:
                # 若尚未写报告且任务需要，自动补一次
                if "report" in (task.deliverables or ["report"]) and not ctx.state.artifacts.get("report"):
                    if "llm_render_report" in allowed:
                        obs, ok = self._run_tool(ctx, "llm_render_report", {}, i, result, fail_counts)
                        history.append({"role": "user", "content": f"Observation: {obs}"})
                        if not ok:
                            result.error = "收尾写报告失败"
                            break
                result.finished = True
                result.final_answer = final_answer or "任务完成"
                if on_progress:
                    on_progress(progress_end, "ReAct 已结束")
                break

            if action not in allowed:
                obs = f"错误：未知工具 `{action}`。请从目录中选择，或 finish。"
                result.steps.append(
                    ReActTraceStep(i, thought, action, action_input, obs, success=False)
                )
                history.append({"role": "user", "content": f"Observation: {obs}\n请修正后继续输出 JSON。"})
                continue

            label = STEP_LABELS.get(action, action)
            if on_progress:
                on_progress(pct, f"ReAct：{label}")

            obs, ok = self._run_tool(ctx, action, action_input, i, result, fail_counts, thought=thought)
            history.append(
                {
                    "role": "user",
                    "content": (
                        f"Observation: {obs}\n"
                        "若任务未完成请继续输出下一轮 JSON；若已完成请 action=finish。"
                    ),
                }
            )

            if fail_counts.get(action, 0) >= 3:
                result.error = f"工具 {action} 连续失败次数过多"
                break
        else:
            result.error = result.error or f"达到 ReAct 最大步数 {self.max_steps}"

        # 强制补报告（未 finish 但已有分析结果时）
        if not ctx.state.artifacts.get("report") and result.plan_steps and "llm_render_report" in allowed:
            obs, ok = self._run_tool(ctx, "llm_render_report", {}, len(result.steps) + 1, result, fail_counts)
            if ok and not result.finished:
                result.finished = True
                result.final_answer = result.final_answer or "已自动补写报告并结束"

        return result

    def _run_tool(
        self,
        ctx: RunContext,
        tool: str,
        action_input: dict[str, Any],
        index: int,
        result: ReActResult,
        fail_counts: dict[str, int],
        *,
        thought: str = "",
    ) -> tuple[str, bool]:
        step = {
            "id": f"react_{index}_{tool}",
            "tool": tool,
            "args": dict(action_input or {}),
            "depends_on": [],
        }
        tool_result = self.executor.run_step(ctx, step)
        ok = bool(tool_result.success)
        if ok:
            fail_counts[tool] = 0
            result.plan_steps.append(step)
            ctx.state.completed_steps.append(step["id"])
            if tool == "llm_render_report":
                ctx.state.report_source = "llm"
            obs = tool_result.message or "成功"
            if tool_result.outputs:
                keys = list(tool_result.outputs.keys())[:8]
                obs += f" | outputs={keys}"
            if tool_result.metrics:
                # 只展示少量指标，避免上下文爆炸
                metric_items = list(tool_result.metrics.items())[:6]
                obs += f" | metrics={dict(metric_items)}"
        else:
            fail_counts[tool] = fail_counts.get(tool, 0) + 1
            obs = f"失败: {tool_result.error or tool_result.message or 'unknown'}"
            ctx.state.errors.append({"step": step["id"], "attempt": fail_counts[tool], "error": tool_result.error})

        obs = _truncate(obs)
        result.steps.append(
            ReActTraceStep(
                index=index,
                thought=thought,
                action=tool,
                action_input=dict(action_input or {}),
                observation=obs,
                success=ok,
            )
        )
        return obs, ok
