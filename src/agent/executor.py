from __future__ import annotations

import time
from typing import Any

from src.run_context import RunContext
from src.tools.base import ToolResult
from src.tools.registry import ToolRegistry


class Executor:
    def __init__(self, registry: ToolRegistry):
        self.registry = registry

    def run_step(self, ctx: RunContext, step: dict[str, Any]) -> ToolResult:
        tool_name = step["tool"]
        args = dict(step.get("args") or {})
        tool = self.registry.get(tool_name)
        ctx.logger.info("执行步骤 %s -> %s args=%s", step.get("id"), tool_name, args)
        started = time.time()
        try:
            result = tool.run(ctx, **args)
        except Exception as e:
            result = ToolResult(success=False, error=str(e), message=f"工具异常: {e}")
        elapsed_ms = int((time.time() - started) * 1000)
        ctx.logger.info(
            "步骤 %s 完成 success=%s elapsed_ms=%s msg=%s",
            step.get("id"),
            result.success,
            elapsed_ms,
            result.message or result.error,
        )
        if result.outputs:
            ctx.state.artifacts.update(result.outputs)
        if result.metrics:
            ctx.metric_store.update(result.metrics)
            ctx.state.metrics.update(result.metrics)
        return result
