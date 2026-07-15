from __future__ import annotations

from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from src.agent.orchestrator import Orchestrator
    from src.agent.state import AgentState

ProgressCallback = Callable[[float, str], None]


def run_with_progress(
    orch: "Orchestrator",
    on_progress: ProgressCallback | None = None,
    only_step: str | None = None,
    raw_task_text: str | None = None,
    agent_mode: str | None = None,
) -> "AgentState":
    """
    入口：用 LangGraph 编排主流程。

    AUTH → PROFILE → SCHEMA_MAP → PARSE
      ├─ plan_execute: PLAN → EXECUTE* → CRITIC
      └─ react: THINK ⇄ ACT → FINALIZE → CRITIC
    """
    from src.agent.langgraph_flow import run_with_langgraph

    return run_with_langgraph(
        orch,
        on_progress=on_progress,
        only_step=only_step,
        raw_task_text=raw_task_text,
        agent_mode=agent_mode,
    )
