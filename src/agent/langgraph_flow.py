from __future__ import annotations

import json
from typing import Any, Callable, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from src.agent.planner import TaskPlan
from src.agent.react_loop import REACT_TOOLS, ReActResult, ReActTraceStep, _schema_brief, _truncate
from src.agent.step_labels import STEP_LABELS
from src.data_resolver import SchemaSummary, build_schema_summary
from src.infra.llm_prompts import load_prompt
from src.tools.catalog import catalog_as_prompt_text, export_tool_catalog

ProgressCallback = Callable[[float, str], None]


class GraphState(TypedDict, total=False):
    """LangGraph 可序列化状态；重对象挂在 Orchestrator 上通过闭包访问。"""

    mode: str
    status: str
    message: str
    progress: float
    halt: bool
    step_index: int
    react_round: int
    react_history: list[dict[str, str]]
    react_trace: list[dict[str, Any]]
    react_fail_counts: dict[str, int]
    current_thought: str
    current_action: str
    current_action_input: dict[str, Any]
    final_answer: str
    plan_source: str
    react_done: bool


def _emit(on_progress: ProgressCallback | None, pct: float, msg: str) -> dict[str, Any]:
    if on_progress:
        on_progress(min(max(pct, 0.0), 1.0), msg)
    return {"progress": pct, "message": msg}


def build_agent_graph(
    orch: Any,
    *,
    on_progress: ProgressCallback | None = None,
    raw_task_text: str | None = None,
    only_step: str | None = None,
):
    """编译数据分析 Agent 的 LangGraph（Plan-Execute / ReAct）。"""

    def node_auth(state: GraphState) -> dict[str, Any]:
        orch.state.status = "AUTH_CHECK"
        upd = _emit(on_progress, 0.02, "校验 API 密钥...")
        auth = orch.ensure_auth()
        if not auth.ok:
            orch.state.status = "BLOCKED"
            orch.state.errors.append({"stage": "auth", "detail": auth.message})
            orch._persist_state()
            return {
                **upd,
                **_emit(on_progress, 1.0, f"无法启动：{auth.message}"),
                "status": "BLOCKED",
                "halt": True,
            }
        orch.state.llm_model = auth.model
        orch.logger.info(
            "开始任务 task_id=%s run_id=%s model=%s mode=%s engine=langgraph",
            orch.task.task_id,
            orch.run_id,
            auth.model,
            state.get("mode"),
        )
        return {**upd, "status": "AUTH_OK", "halt": False}

    def node_profile(state: GraphState) -> dict[str, Any]:
        orch.state.status = "PROFILE"
        upd = _emit(on_progress, 0.06, "探查数据结构...")
        schema = build_schema_summary(orch.data_inputs, orch.config.get("schema_hints"))
        orch.ctx.schema = schema
        (orch.run_dir / "schema_summary.json").write_text(
            json.dumps(schema.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return {**upd, "status": "PROFILE"}

    def node_schema_map(state: GraphState) -> dict[str, Any]:
        orch.state.status = "LLM_SCHEMA_MAP"
        upd = _emit(on_progress, 0.09, "LLM 识别数据字段...")
        goal_text = raw_task_text or orch.task.goal or orch.task.raw_text
        schema: SchemaSummary = orch.ctx.schema
        try:
            schema_map = orch.map_schema_with_llm(schema, goal_text=goal_text or "")
            mapping_path = orch.run_dir / "column_mapping.json"
            mapping_path.write_text(json.dumps(schema_map, ensure_ascii=False, indent=2), encoding="utf-8")
            orch.state.artifacts["column_mapping"] = str(mapping_path)
            (orch.run_dir / "schema_summary.json").write_text(
                json.dumps(schema.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            orch.logger.warning("字段映射失败，将仅用规则 hints: %s", e)
            from src.agent.schema_mapper import rule_mapping_from_table

            table = schema.primary()
            fallback = rule_mapping_from_table(table, orch.config.get("schema_hints")) if table else {}
            orch.ctx.extras["column_mapping"] = fallback
            if table:
                table.mapped_columns = dict(fallback)
            payload = {
                "table_kind": table.table_kind if table else "unknown",
                "mapping": fallback,
                "source": "rules_fallback",
                "notes": [str(e)],
            }
            (orch.run_dir / "column_mapping.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            orch.state.artifacts["column_mapping"] = str(orch.run_dir / "column_mapping.json")
        return {**upd, "status": "LLM_SCHEMA_MAP"}

    def node_parse_task(state: GraphState) -> dict[str, Any]:
        orch.state.status = "LLM_PARSE_TASK"
        upd = _emit(on_progress, 0.12, "LLM 理解任务要求...")
        goal_text = raw_task_text or orch.task.goal or orch.task.raw_text
        schema: SchemaSummary = orch.ctx.schema
        try:
            parsed = orch.parse_task_with_llm(goal_text, schema)
            orch.task = parsed
            orch.ctx.task = parsed
            orch.state.task_id = parsed.task_id
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
            return {**upd, "status": "LLM_PARSE_TASK", "halt": False}
        except Exception as e:
            orch.state.status = "FAILED"
            orch.state.errors.append({"stage": "task_parser", "error": str(e)})
            orch._persist_state()
            return {
                **upd,
                **_emit(on_progress, 1.0, f"任务理解失败：{e}"),
                "status": "FAILED",
                "halt": True,
            }

    def node_plan(state: GraphState) -> dict[str, Any]:
        orch.state.status = "LLM_PLAN"
        upd = _emit(on_progress, 0.18, "LLM 规划分析步骤...")
        schema: SchemaSummary = orch.ctx.schema
        try:
            plan, feas, source = orch.plan_with_llm(schema)
            orch.state.plan_source = source
            orch.state.feasibility = plan.feasibility
            orch.state.plan = plan.steps
            orch.ctx.extras["task_plan"] = plan
            orch._save_snapshots(plan)
        except Exception as e:
            orch.state.status = "FAILED"
            orch.state.errors.append({"stage": "planner", "error": str(e)})
            orch._persist_state()
            return {
                **upd,
                **_emit(on_progress, 1.0, f"规划失败：{e}"),
                "status": "FAILED",
                "halt": True,
                "plan_source": "failed",
            }

        msg = f"规划完成（{source}，可行性：{plan.feasibility}）"
        if plan.feasibility == "infeasible" and orch.config.get("orchestrator", {}).get("stop_on_infeasible", True):
            orch.state.status = "INFEASIBLE"
            orch.state.errors.append({"stage": "feasibility", "detail": plan.notes})
            orch._persist_state()
            return {
                **_emit(on_progress, 1.0, "任务不可行"),
                "status": "INFEASIBLE",
                "halt": True,
                "plan_source": source,
                "step_index": 0,
            }
        if plan.feasibility == "partial":
            orch.logger.warning("部分可行，将降级执行: %s", plan.notes)

        steps = list(plan.steps)
        if only_step:
            steps = [s for s in steps if s["id"] == only_step or s["tool"] == only_step]
            plan.steps = steps
            orch.state.plan = steps
            orch.ctx.extras["task_plan"] = plan
        return {
            **_emit(on_progress, 0.22, msg),
            "status": "LLM_PLAN",
            "halt": False,
            "plan_source": source,
            "step_index": 0,
        }

    def node_execute_one(state: GraphState) -> dict[str, Any]:
        plan: TaskPlan = orch.ctx.extras.get("task_plan")
        steps = plan.steps if plan else orch.state.plan
        idx = int(state.get("step_index") or 0)
        max_retries = int(orch.config.get("orchestrator", {}).get("max_retries", 2))
        total = max(len(steps), 1)

        # 跳过已完成
        while idx < len(steps) and steps[idx]["id"] in orch.state.completed_steps and not only_step:
            idx += 1
        if idx >= len(steps):
            return {"status": "EXECUTE_DONE", "step_index": idx, "halt": False}

        step = steps[idx]
        step_id = step["id"]
        label = STEP_LABELS.get(step_id) or STEP_LABELS.get(step.get("tool", ""), step.get("tool", step_id))
        step_pct = 0.22 + 0.68 * (idx / total)
        orch.state.status = "EXECUTE"
        orch.state.current_step = step_id
        orch._persist_state()
        _emit(on_progress, step_pct, f"正在执行：{label}（{idx + 1}/{total}）")

        attempt = 0
        while True:
            attempt += 1
            result = orch.executor.run_step(orch.ctx, step)
            if result.success:
                orch.state.completed_steps.append(step_id)
                if step.get("tool") == "llm_render_report":
                    orch.state.report_source = "llm"
                orch._persist_state()
                done_pct = 0.22 + 0.68 * ((idx + 1) / total)
                return {
                    **_emit(on_progress, done_pct, f"已完成：{label}（{idx + 1}/{total}）"),
                    "status": "EXECUTE",
                    "step_index": idx + 1,
                    "halt": False,
                }
            orch.state.errors.append({"step": step_id, "attempt": attempt, "error": result.error})
            orch._persist_state()
            if attempt > max_retries:
                orch.state.status = "FAILED"
                orch.logger.error("步骤失败且超过重试: %s %s", step_id, result.error)
                orch._save_llm_usage()
                return {
                    **_emit(on_progress, 1.0, f"失败：{label}"),
                    "status": "FAILED",
                    "step_index": idx,
                    "halt": True,
                }
            orch.logger.warning("步骤失败，重试 %s/%s: %s", attempt, max_retries, result.error)

    def node_react_init(state: GraphState) -> dict[str, Any]:
        orch.state.status = "REACT"
        orch.state.plan_source = "react"
        orch.ensure_auth()
        schema: SchemaSummary = orch.ctx.schema
        catalog = [c for c in export_tool_catalog(orch.registry) if c["name"] in REACT_TOOLS]
        history = [
            {"role": "system", "content": load_prompt("system_react.md")},
            {
                "role": "user",
                "content": (
                    "开始 ReAct 任务。\n"
                    f"用户目标：{orch.task.goal or orch.task.raw_text}\n"
                    f"交付物：{orch.task.deliverables}\n"
                    f"数据概况：{json.dumps(_schema_brief(schema), ensure_ascii=False)}\n"
                    f"{catalog_as_prompt_text(catalog)}\n"
                    "请输出第一轮 JSON（thought/action/action_input）。"
                ),
            },
        ]
        orch.ctx.extras["react_result"] = ReActResult(finished=False)
        return {
            **_emit(on_progress, 0.18, "ReAct（LangGraph）：边想边做..."),
            "status": "REACT",
            "plan_source": "react",
            "react_round": 0,
            "react_history": history,
            "react_trace": [],
            "react_fail_counts": {},
            "halt": False,
            "react_done": False,
        }

    def node_react_think(state: GraphState) -> dict[str, Any]:
        max_steps = int(orch.config.get("orchestrator", {}).get("react_max_steps", 12))
        rnd = int(state.get("react_round") or 0) + 1
        if rnd > max_steps:
            return {
                **_emit(on_progress, 0.9, f"达到 ReAct 最大步数 {max_steps}"),
                "status": "REACT_MAX",
                "react_round": rnd,
                "current_action": "finish",
                "final_answer": state.get("final_answer") or f"达到最大步数 {max_steps}",
                "halt": False,
            }
        pct = 0.18 + 0.74 * ((rnd - 1) / max_steps)
        _emit(on_progress, pct, f"ReAct 第 {rnd}/{max_steps} 轮：思考中...")
        history = list(state.get("react_history") or [])
        assert orch._gateway is not None
        try:
            decision = orch._gateway.chat_json(history, stage=f"react_step_{rnd}")
        except Exception as e:
            orch.state.errors.append({"stage": "react", "error": str(e)})
            return {
                **_emit(on_progress, 1.0, f"ReAct LLM 调用失败：{e}"),
                "status": "FAILED",
                "halt": True,
                "react_round": rnd,
                "current_action": "finish",
            }
        thought = str(decision.get("thought") or "")
        action = str(decision.get("action") or "").strip()
        action_input = decision.get("action_input") if isinstance(decision.get("action_input"), dict) else {}
        final_answer = str(decision.get("final_answer") or "")
        history.append({"role": "assistant", "content": json.dumps(decision, ensure_ascii=False)})
        return {
            "react_round": rnd,
            "react_history": history,
            "current_thought": thought,
            "current_action": action,
            "current_action_input": action_input,
            "final_answer": final_answer,
            "status": "REACT_THINK",
            "halt": False,
            **_emit(on_progress, pct, f"ReAct：决定 {action or 'finish'}"),
        }

    def node_react_act(state: GraphState) -> dict[str, Any]:
        action = str(state.get("current_action") or "").strip()
        thought = str(state.get("current_thought") or "")
        action_input = dict(state.get("current_action_input") or {})
        history = list(state.get("react_history") or [])
        trace = list(state.get("react_trace") or [])
        fail_counts = dict(state.get("react_fail_counts") or {})
        rnd = int(state.get("react_round") or 0)
        react_result: ReActResult = orch.ctx.extras.get("react_result") or ReActResult(finished=False)
        catalog_names = {c["name"] for c in export_tool_catalog(orch.registry) if c["name"] in REACT_TOOLS}

        if action in {"finish", "done", "stop", "complete"}:
            if "report" in (orch.task.deliverables or ["report"]) and not orch.state.artifacts.get("report"):
                if "llm_render_report" in catalog_names:
                    obs, ok = _exec_react_tool(
                        orch, "llm_render_report", {}, rnd, thought, react_result, fail_counts, trace
                    )
                    history.append({"role": "user", "content": f"Observation: {obs}"})
                    if not ok:
                        orch.state.status = "FAILED"
                        return {
                            **_emit(on_progress, 1.0, "收尾写报告失败"),
                            "status": "FAILED",
                            "halt": True,
                            "react_history": history,
                            "react_trace": trace,
                            "react_fail_counts": fail_counts,
                        }
            react_result.finished = True
            react_result.final_answer = state.get("final_answer") or "任务完成"
            orch.ctx.extras["react_result"] = react_result
            return {
                **_emit(on_progress, 0.92, "ReAct 已结束"),
                "status": "REACT_DONE",
                "halt": False,
                "react_done": True,
                "react_history": history,
                "react_trace": trace,
                "react_fail_counts": fail_counts,
                "current_action": "finish",
            }

        if action not in catalog_names:
            obs = f"错误：未知工具 `{action}`。请从目录中选择，或 finish。"
            trace.append(
                ReActTraceStep(rnd, thought, action, action_input, obs, success=False).to_dict()
            )
            history.append({"role": "user", "content": f"Observation: {obs}\n请修正后继续输出 JSON。"})
            return {
                "status": "REACT_ACT",
                "halt": False,
                "react_done": False,
                "react_history": history,
                "react_trace": trace,
                "react_fail_counts": fail_counts,
            }

        label = STEP_LABELS.get(action, action)
        _emit(on_progress, float(state.get("progress") or 0.5), f"ReAct：{label}")
        obs, ok = _exec_react_tool(orch, action, action_input, rnd, thought, react_result, fail_counts, trace)
        history.append(
            {
                "role": "user",
                "content": f"Observation: {obs}\n若任务未完成请继续输出下一轮 JSON；若已完成请 action=finish。",
            }
        )
        orch.ctx.extras["react_result"] = react_result
        if fail_counts.get(action, 0) >= 3:
            orch.state.status = "FAILED"
            orch.state.errors.append({"stage": "react", "error": f"工具 {action} 连续失败次数过多"})
            return {
                **_emit(on_progress, 1.0, f"工具 {action} 连续失败过多"),
                "status": "FAILED",
                "halt": True,
                "react_history": history,
                "react_trace": trace,
                "react_fail_counts": fail_counts,
            }
        return {
            "status": "REACT_ACT",
            "halt": False,
            "react_done": False,
            "react_history": history,
            "react_trace": trace,
            "react_fail_counts": fail_counts,
        }

    def node_react_finalize(state: GraphState) -> dict[str, Any]:
        react_result: ReActResult = orch.ctx.extras.get("react_result") or ReActResult(finished=False)
        # 自动补报告
        if not orch.state.artifacts.get("report") and react_result.plan_steps:
            trace = list(state.get("react_trace") or [])
            fail_counts = dict(state.get("react_fail_counts") or {})
            obs, ok = _exec_react_tool(
                orch,
                "llm_render_report",
                {},
                int(state.get("react_round") or 0) + 1,
                "auto finalize report",
                react_result,
                fail_counts,
                trace,
            )
            if ok:
                react_result.finished = True
                react_result.final_answer = react_result.final_answer or "已自动补写报告并结束"
            orch.ctx.extras["react_result"] = react_result

        plan = react_result.as_task_plan(orch.task)
        orch.state.plan = plan.steps
        orch.state.feasibility = plan.feasibility
        orch.ctx.extras["task_plan"] = plan
        orch._save_snapshots(plan)
        trace_path = orch.run_dir / "react_trace.json"
        payload = react_result.to_dict()
        payload["trace"] = state.get("react_trace") or payload.get("steps")
        payload["engine"] = "langgraph"
        trace_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        orch.state.artifacts["react_trace"] = str(trace_path)

        if react_result.error and not react_result.finished and not orch.state.artifacts.get("report"):
            orch.state.status = "FAILED"
            orch.state.errors.append({"stage": "react", "error": react_result.error})
            orch._save_llm_usage()
            orch._persist_state()
            return {
                **_emit(on_progress, 1.0, f"ReAct 失败：{react_result.error}"),
                "status": "FAILED",
                "halt": True,
            }
        return {"status": "REACT_FINALIZED", "halt": False, "plan_source": "react"}

    def node_critic(state: GraphState) -> dict[str, Any]:
        plan: TaskPlan | None = orch.ctx.extras.get("task_plan")
        if plan is None:
            plan = TaskPlan(
                task_id=orch.task.task_id,
                feasibility="partial",
                steps=orch.state.plan,
                acceptance_checks=[{"type": "artifact_exists", "key": "report"}],
            )
        orch.state.status = "CRITIC"
        _emit(on_progress, 0.95, "正在验收分析结果...")
        report = orch.critic.validate_plan_acceptance(orch.ctx, plan)
        (orch.run_dir / "validation.json").write_text(
            json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if not report.passed:
            orch.state.status = "VALIDATION_FAILED"
            orch.state.errors.append({"stage": "critic", "detail": report.to_dict()})
            orch.logger.error("验收未通过: %s", report.to_dict())
            status = "VALIDATION_FAILED"
            msg = "验收未通过"
        else:
            orch.state.status = "DONE"
            orch.logger.info("任务完成")
            status = "DONE"
            msg = "分析完成"
        if orch.task.needs_human_review:
            orch.state.human_gates.append("final_report")
        orch._save_llm_usage()
        orch._persist_state()
        return {**_emit(on_progress, 1.0, msg), "status": status, "halt": True}

    def route_after_auth(state: GraphState) -> Literal["profile", "__end__"]:
        return "__end__" if state.get("halt") else "profile"

    def route_after_parse(state: GraphState) -> Literal["plan", "react_init", "__end__"]:
        if state.get("halt"):
            return "__end__"
        return "react_init" if state.get("mode") == "react" else "plan"

    def route_after_plan(state: GraphState) -> Literal["execute_one", "__end__"]:
        return "__end__" if state.get("halt") else "execute_one"

    def route_after_execute(state: GraphState) -> Literal["execute_one", "critic", "__end__"]:
        if state.get("halt"):
            return "__end__"
        plan: TaskPlan | None = orch.ctx.extras.get("task_plan")
        steps = plan.steps if plan else orch.state.plan
        idx = int(state.get("step_index") or 0)
        if idx < len(steps):
            return "execute_one"
        return "critic"

    def route_after_react_think(state: GraphState) -> Literal["react_act", "__end__"]:
        return "__end__" if state.get("halt") else "react_act"

    def route_after_react_act(state: GraphState) -> Literal["react_think", "react_finalize", "__end__"]:
        if state.get("halt"):
            return "__end__"
        if state.get("react_done") or state.get("current_action") in {"finish", "done", "stop", "complete"}:
            # finish 已在 act 中处理完时走 finalize
            if state.get("react_done") or state.get("status") == "REACT_DONE":
                return "react_finalize"
            # think 直接给出 finish 且 act 设了 REACT_DONE
            return "react_finalize"
        return "react_think"

    def route_after_react_finalize(state: GraphState) -> Literal["critic", "__end__"]:
        return "__end__" if state.get("halt") else "critic"

    g = StateGraph(GraphState)
    g.add_node("auth", node_auth)
    g.add_node("profile", node_profile)
    g.add_node("schema_map", node_schema_map)
    g.add_node("parse_task", node_parse_task)
    g.add_node("plan", node_plan)
    g.add_node("execute_one", node_execute_one)
    g.add_node("react_init", node_react_init)
    g.add_node("react_think", node_react_think)
    g.add_node("react_act", node_react_act)
    g.add_node("react_finalize", node_react_finalize)
    g.add_node("critic", node_critic)

    g.add_edge(START, "auth")
    g.add_conditional_edges("auth", route_after_auth, {"profile": "profile", "__end__": END})
    g.add_edge("profile", "schema_map")
    g.add_edge("schema_map", "parse_task")
    g.add_conditional_edges(
        "parse_task",
        route_after_parse,
        {"plan": "plan", "react_init": "react_init", "__end__": END},
    )
    g.add_conditional_edges("plan", route_after_plan, {"execute_one": "execute_one", "__end__": END})
    g.add_conditional_edges(
        "execute_one",
        route_after_execute,
        {"execute_one": "execute_one", "critic": "critic", "__end__": END},
    )
    g.add_edge("react_init", "react_think")
    g.add_conditional_edges(
        "react_think",
        route_after_react_think,
        {"react_act": "react_act", "__end__": END},
    )
    g.add_conditional_edges(
        "react_act",
        route_after_react_act,
        {"react_think": "react_think", "react_finalize": "react_finalize", "__end__": END},
    )
    g.add_conditional_edges(
        "react_finalize",
        route_after_react_finalize,
        {"critic": "critic", "__end__": END},
    )
    g.add_edge("critic", END)
    return g.compile()


def _exec_react_tool(
    orch: Any,
    tool: str,
    action_input: dict[str, Any],
    index: int,
    thought: str,
    react_result: ReActResult,
    fail_counts: dict[str, int],
    trace: list[dict[str, Any]],
) -> tuple[str, bool]:
    step = {
        "id": f"react_{index}_{tool}",
        "tool": tool,
        "args": dict(action_input or {}),
        "depends_on": [],
    }
    tool_result = orch.executor.run_step(orch.ctx, step)
    ok = bool(tool_result.success)
    if ok:
        fail_counts[tool] = 0
        react_result.plan_steps.append(step)
        orch.state.completed_steps.append(step["id"])
        if tool == "llm_render_report":
            orch.state.report_source = "llm"
        obs = tool_result.message or "成功"
        if tool_result.outputs:
            obs += f" | outputs={list(tool_result.outputs.keys())[:8]}"
        if tool_result.metrics:
            obs += f" | metrics={dict(list(tool_result.metrics.items())[:6])}"
    else:
        fail_counts[tool] = fail_counts.get(tool, 0) + 1
        obs = f"失败: {tool_result.error or tool_result.message or 'unknown'}"
        orch.state.errors.append({"step": step["id"], "attempt": fail_counts[tool], "error": tool_result.error})
    obs = _truncate(obs)
    step_trace = ReActTraceStep(index, thought, tool, dict(action_input or {}), obs, success=ok)
    react_result.steps.append(step_trace)
    trace.append(step_trace.to_dict())
    return obs, ok


def run_with_langgraph(
    orch: Any,
    *,
    on_progress: ProgressCallback | None = None,
    only_step: str | None = None,
    raw_task_text: str | None = None,
    agent_mode: str | None = None,
):
    mode = (agent_mode or orch.config.get("orchestrator", {}).get("mode") or "plan_execute").strip().lower()
    if mode in {"react", "re-act", "reasoning_acting"}:
        mode = "react"
    else:
        mode = "plan_execute"
    orch.state.plan_source = mode
    orch.ctx.extras["agent_mode"] = mode
    orch.ctx.extras["engine"] = "langgraph"

    app = build_agent_graph(
        orch,
        on_progress=on_progress,
        raw_task_text=raw_task_text,
        only_step=only_step,
    )
    app.invoke(
        {
            "mode": mode,
            "status": "INIT",
            "message": "",
            "progress": 0.0,
            "halt": False,
            "step_index": 0,
            "react_round": 0,
            "react_history": [],
            "react_trace": [],
            "react_fail_counts": {},
            "plan_source": mode,
        },
        config={"recursion_limit": 80},
    )
    return orch.state
