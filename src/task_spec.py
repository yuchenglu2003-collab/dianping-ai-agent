from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TaskSpec:
    task_id: str
    goal: str = ""
    data: list[dict[str, Any]] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)
    acceptance: dict[str, Any] = field(default_factory=dict)
    params: dict[str, Any] = field(default_factory=dict)
    needs_human_review: bool = False
    report: dict[str, Any] = field(default_factory=dict)
    raw_path: str | None = None
    raw_text: str = ""

    def merged_params(self, defaults: dict[str, Any]) -> dict[str, Any]:
        merged = dict(defaults or {})
        merged.update(self.params or {})
        return merged
