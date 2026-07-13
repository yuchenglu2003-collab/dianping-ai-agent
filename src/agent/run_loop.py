from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from src.agent.step_labels import STEP_LABELS
from src.data_resolver import build_schema_summary

if TYPE_CHECKING:
    from src.agent.orchestrator import Orchestrator
    from src.agent.state import AgentState

ProgressCallback = Callable[[float, str], None]


def run_with_progress(
    orch: "Orchestrator",
    on_progress: ProgressCallback | None = None,
    only_step: str | None = None,
    raw_task_text: str | None = None,
) -> "AgentState":
    """
    LLM 驱动主流程：
    AUTH → PROFILE → LLM_SCHEMA_MAP → LLM_PARSE_TASK → LLM_PLAN → EXECUTE → CRITIC → DONE
    （报告步骤在 plan 内由 llm_render_report 完成）
    """

    def _progress(pct: float, msg: str) -> None:
        if on_progress:
            on_progress(min(max(pct, 0.0), 1.0), msg)

    # ---- AUTH ----
    orch.state.status = "AUTH_CHECK"
    _progress(0.02, "校验 API 密钥...")
    auth = orch.ensure_auth()
    if not auth.ok:
        orch.state.status = "BLOCKED"
        orch.state.errors.append({"stage": "auth", "detail": auth.message})
        orch._persist_state()
        _progress(1.0, f"无法启动：{auth.message}")
        return orch.state

    orch.state.llm_model = auth.model
    orch.logger.info("开始任务 task_id=%s run_id=%s model=%s", orch.task.task_id, orch.run_id, auth.model)

    # ---- PROFILE ----
    orch.state.status = "PROFILE"
    _progress(0.06, "探查数据结构...")
    schema = build_schema_summary(orch.data_inputs, orch.config.get("schema_hints"))
    orch.ctx.schema = schema
    (orch.run_dir / "schema_summary.json").write_text(
        json.dumps(schema.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # ---- LLM SCHEMA MAP ----
    orch.state.status = "LLM_SCHEMA_MAP"
    _progress(0.09, "LLM 识别数据字段...")
    goal_text = raw_task_text or orch.task.goal or orch.task.raw_text
    try:
        schema_map = orch.map_schema_with_llm(schema, goal_text=goal_text or "")
        mapping_path = orch.run_dir / "column_mapping.json"
        mapping_path.write_text(
            json.dumps(schema_map, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        orch.state.artifacts["column_mapping"] = str(mapping_path)
        orch.logger.info(
            "字段映射 source=%s kind=%s mapping=%s",
            schema_map.get("source"),
            schema_map.get("table_kind"),
            schema_map.get("mapping"),
        )
        # 刷新 schema 快照（含 LLM 映射）
        (orch.run_dir / "schema_summary.json").write_text(
            json.dumps(schema.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        orch.logger.warning("字段映射失败，将仅用规则 hints: %s", e)
        # 退回规则映射，避免后续工具完全不认列
        from src.agent.schema_mapper import rule_mapping_from_table

        table = schema.primary()
        fallback = rule_mapping_from_table(table, orch.config.get("schema_hints")) if table else {}
        orch.ctx.extras["column_mapping"] = fallback
        if table:
            table.mapped_columns = dict(fallback)
        (orch.run_dir / "column_mapping.json").write_text(
            json.dumps(
                {"table_kind": table.table_kind if table else "unknown", "mapping": fallback, "source": "rules_fallback", "notes": [str(e)]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        orch.state.artifacts["column_mapping"] = str(orch.run_dir / "column_mapping.json")
    # ---- LLM PARSE TASK ----
    orch.state.status = "LLM_PARSE_TASK"
    _progress(0.12, "LLM 理解任务要求...")
    try:
        parsed = orch.parse_task_with_llm(goal_text, schema)
        orch.task = parsed
        orch.ctx.task = parsed
        orch.state.task_id = parsed.task_id
        # 更新 artifact store 的 task_id 前缀
        orch.ctx.artifact_store.task_id = parsed.task_id
        (orch.run_dir / "task_spec.json").write_text(
            json.dumps(
                {
                    "task_id": parsed.task_id,
                    "goal": parsed.goal,
                    "deliverables": parsed.deliverables,
                    "acceptance": parsed.acceptance,
                    "params": parsed.params,
                    "report": parsed.report,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (orch.run_dir / "task_snapshot.md").write_text(parsed.raw_text or parsed.goal, encoding="utf-8")
    except Exception as e:
        orch.state.status = "FAILED"
        orch.state.errors.append({"stage": "task_parser", "error": str(e)})
        orch._persist_state()
        _progress(1.0, f"任务理解失败：{e}")
        return orch.state

    # ---- LLM PLAN ----
    orch.state.status = "LLM_PLAN"
    _progress(0.18, "LLM 规划分析步骤...")
    try:
        plan, feas, source = orch.plan_with_llm(schema)
        orch.state.plan_source = source
        orch.state.feasibility = plan.feasibility
        orch.state.plan = plan.steps
        orch._save_snapshots(plan)
    except Exception as e:
        orch.state.status = "FAILED"
        orch.state.errors.append({"stage": "planner", "error": str(e)})
        orch._persist_state()
        _progress(1.0, f"规划失败：{e}")
        return orch.state

    _progress(0.22, f"规划完成（{source}，可行性：{plan.feasibility}）")

    if plan.feasibility == "infeasible" and orch.config.get("orchestrator", {}).get("stop_on_infeasible", True):
        orch.state.status = "INFEASIBLE"
        orch.state.errors.append({"stage": "feasibility", "detail": plan.notes})
        orch._persist_state()
        orch.logger.error("任务不可行: %s", plan.notes)
        _progress(1.0, "任务不可行")
        return orch.state

    if plan.feasibility == "partial":
        orch.logger.warning("部分可行，将降级执行: %s", plan.notes)

    # ---- EXECUTE ----
    max_retries = int(orch.config.get("orchestrator", {}).get("max_retries", 2))
    steps = plan.steps
    # 跳过 plan 里多余的开头 profile（已做过），但仍允许执行
    if only_step:
        steps = [s for s in steps if s["id"] == only_step or s["tool"] == only_step]
        if not steps:
            raise ValueError(f"未找到步骤: {only_step}")

    orch.state.status = "EXECUTE"
    total_steps = max(len(steps), 1)
    for idx, step in enumerate(steps):
        step_id = step["id"]
        label = STEP_LABELS.get(step_id) or STEP_LABELS.get(step.get("tool", ""), step.get("tool", step_id))
        step_pct = 0.22 + 0.68 * (idx / total_steps)
        _progress(step_pct, f"正在执行：{label}（{idx + 1}/{total_steps}）")

        if step_id in orch.state.completed_steps and not only_step:
            continue
        orch.state.current_step = step_id
        orch._persist_state()

        attempt = 0
        while True:
            attempt += 1
            result = orch.executor.run_step(orch.ctx, step)
            if result.success:
                orch.state.completed_steps.append(step_id)
                if step.get("tool") == "llm_render_report":
                    orch.state.report_source = "llm"
                orch._persist_state()
                done_pct = 0.22 + 0.68 * ((idx + 1) / total_steps)
                _progress(done_pct, f"已完成：{label}（{idx + 1}/{total_steps}）")
                break
            orch.state.errors.append({"step": step_id, "attempt": attempt, "error": result.error})
            orch._persist_state()
            if attempt > max_retries:
                orch.state.status = "FAILED"
                orch.logger.error("步骤失败且超过重试: %s %s", step_id, result.error)
                _progress(1.0, f"失败：{label}")
                orch._save_llm_usage()
                return orch.state
            orch.logger.warning("步骤失败，重试 %s/%s: %s", attempt, max_retries, result.error)

    # ---- CRITIC ----
    orch.state.status = "CRITIC"
    _progress(0.95, "正在验收分析结果...")
    report = orch.critic.validate_plan_acceptance(orch.ctx, plan)
    (orch.run_dir / "validation.json").write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if not report.passed:
        orch.state.status = "VALIDATION_FAILED"
        orch.state.errors.append({"stage": "critic", "detail": report.to_dict()})
        orch.logger.error("验收未通过: %s", report.to_dict())
        _progress(1.0, "验收未通过")
    else:
        orch.state.status = "DONE"
        orch.logger.info("任务完成")
        _progress(1.0, "分析完成")

    if orch.task.needs_human_review:
        orch.state.human_gates.append("final_report")
        orch.logger.info("等待人工审核: final_report")

    orch._save_llm_usage()
    orch._persist_state()
    return orch.state
