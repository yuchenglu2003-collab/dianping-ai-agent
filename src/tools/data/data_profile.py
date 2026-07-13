from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.data_resolver import build_schema_summary, resolve_data_paths
from src.tools.base import BaseTool, ToolResult


class DataProfileTool(BaseTool):
    name = "data_profile"
    description = "对输入数据做 schema / 缺失 / 分布摘要"

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        paths = [Path(p) for p in ctx.data_inputs]
        if kwargs.get("path"):
            paths = resolve_data_paths(kwargs["path"])

        schema = build_schema_summary(paths, ctx.config.get("schema_hints"))
        ctx.schema = schema

        out = ctx.run_dir / "schema_summary.json" if ctx.run_dir else ctx.artifact_store.report_path("schema_summary", "json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(schema.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

        primary = schema.primary()
        metrics: dict[str, Any] = {"table_count": len(schema.tables)}
        if primary:
            metrics.update(
                {
                    "primary_rows": primary.rows,
                    "primary_cols": len(primary.columns),
                    "primary_table_kind": primary.table_kind,
                }
            )

        return ToolResult(
            success=True,
            outputs={"schema_summary": str(out)},
            metrics=metrics,
            message=f"已探查 {len(schema.tables)} 张表",
        )
