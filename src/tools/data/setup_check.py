from __future__ import annotations

import importlib
from typing import Any

from src.tools.base import BaseTool, ToolResult


REQUIRED_PACKAGES = [
    "pandas",
    "numpy",
    "plotly",
    "jieba",
    "sklearn",
    "yaml",
    "jinja2",
    "httpx",
    "dotenv",
]


class SetupCheckTool(BaseTool):
    name = "setup_check"
    description = "检查 Python 依赖、路径与 API 密钥"

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        missing: list[str] = []
        for pkg in REQUIRED_PACKAGES:
            mod = "yaml" if pkg == "yaml" else ("dotenv" if pkg == "dotenv" else pkg)
            try:
                importlib.import_module(mod)
            except ImportError:
                missing.append(pkg)

        path_ok: dict[str, bool] = {}
        for key, value in ctx.paths.items():
            from pathlib import Path

            p = Path(value)
            path_ok[key] = p.exists()
            if not p.exists() and key in {"raw", "clean", "artifacts", "logs"}:
                p.mkdir(parents=True, exist_ok=True)
                path_ok[key] = True

        # 优先信任本轮已通过的鉴权（UI 密钥不会写进 .env）
        auth_info = ctx.extras.get("auth") or {}
        gateway = ctx.extras.get("llm_gateway")
        if gateway is not None or auth_info.get("api_key_set"):
            key_ok = True
            key_msg = auth_info.get("message") or "本轮已通过鉴权（UI / 环境变量）"
        else:
            from src.agent.auth_gate import require_api_key

            ui_key = ctx.extras.get("ui_api_key") or None
            auth = require_api_key(
                project_root=ctx.project_root,
                ui_api_key=ui_key,
                config=ctx.config,
                ping=False,
            )
            key_ok = auth.ok
            key_msg = auth.message

        ok = not missing and key_ok
        report = ctx.artifact_store.report_path("setup_check")
        lines = [
            "# 环境自检报告",
            "",
            f"- 缺失依赖: {missing or '无'}",
            f"- 路径检查: {path_ok}",
            f"- API 密钥: {'OK - ' + key_msg if key_ok else 'MISSING - ' + key_msg}",
            f"- 结果: {'PASS' if ok else 'FAIL'}",
        ]
        report.write_text("\n".join(lines), encoding="utf-8")
        return ToolResult(
            success=ok,
            outputs={"setup_report": str(report)},
            metrics={"missing_packages": len(missing), "api_key_ok": int(key_ok)},
            message="环境检查完成" if ok else f"失败: missing={missing}, key_ok={key_ok}",
            error=None if ok else f"缺少依赖或 API 密钥: missing={missing}, key={key_msg}",
        )
