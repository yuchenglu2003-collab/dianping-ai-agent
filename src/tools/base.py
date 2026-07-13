from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.run_context import RunContext


@dataclass
class ToolResult:
    success: bool
    outputs: dict[str, str] = field(default_factory=dict)
    metrics: dict[str, float | int | str] = field(default_factory=dict)
    message: str = ""
    error: str | None = None


class BaseTool(ABC):
    name: str = "base"
    description: str = ""
    required_columns: list[str] = []
    required_any_columns: list[list[str]] = []  # 任一组合满足即可

    @abstractmethod
    def run(self, ctx: "RunContext", **kwargs: Any) -> ToolResult:
        raise NotImplementedError
