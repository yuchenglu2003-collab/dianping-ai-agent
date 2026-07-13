from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agent.state import AgentState
from src.data_resolver import SchemaSummary
from src.infra.artifact_store import ArtifactStore
from src.infra.metric_store import MetricStore
from src.task_spec import TaskSpec


@dataclass
class RunContext:
    run_id: str
    project_root: Path
    task: TaskSpec
    data_inputs: list[Path]
    config: dict[str, Any]
    state: AgentState
    logger: logging.Logger
    artifact_store: ArtifactStore
    metric_store: MetricStore
    schema: SchemaSummary | None = None
    run_dir: Path | None = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def params(self) -> dict[str, Any]:
        return self.task.merged_params(self.config.get("defaults", {}))

    @property
    def paths(self) -> dict[str, str]:
        return self.config.get("paths", {})
