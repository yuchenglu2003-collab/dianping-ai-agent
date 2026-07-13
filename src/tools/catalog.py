from __future__ import annotations

from typing import Any

from src.tools.base import BaseTool
from src.tools.registry import ToolRegistry


def export_tool_catalog(registry: ToolRegistry) -> list[dict[str, Any]]:
    """导出供 LLM Planner 阅读的工具目录。"""
    catalog: list[dict[str, Any]] = []
    for name, tool in registry.all().items():
        catalog.append(
            {
                "name": tool.name,
                "description": tool.description or name,
                "required_columns": list(getattr(tool, "required_columns", []) or []),
                "required_any_columns": list(getattr(tool, "required_any_columns", []) or []),
            }
        )
    return catalog


def catalog_as_prompt_text(catalog: list[dict[str, Any]]) -> str:
    lines = ["可用工具目录："]
    for item in catalog:
        req = item.get("required_columns") or []
        any_req = item.get("required_any_columns") or []
        lines.append(
            f"- {item['name']}: {item['description']}"
            f" | required={req} | required_any={any_req}"
        )
    return "\n".join(lines)
