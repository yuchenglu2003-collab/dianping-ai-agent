from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AgentState:
    run_id: str
    task_id: str
    task_file: str | None = None
    data_inputs: list[str] = field(default_factory=list)
    current_step: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    plan: list[dict[str, Any]] = field(default_factory=list)
    artifacts: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[dict[str, Any]] = field(default_factory=list)
    human_gates: list[str] = field(default_factory=list)
    feasibility: str = "unknown"
    status: str = "INIT"
    llm_model: str | None = None
    plan_source: str = "unknown"
    report_source: str = "unknown"
    llm_usage: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentState":
        allowed = set(cls.__dataclass_fields__)
        payload = {k: v for k, v in data.items() if k in allowed}
        return cls(**payload)
