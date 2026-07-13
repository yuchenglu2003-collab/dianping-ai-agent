from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.agent.planner import TaskPlan
from src.run_context import RunContext


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class ValidationReport:
    passed: bool
    checks: list[CheckResult] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in self.checks],
            "warnings": self.warnings,
        }


class Critic:
    def validate_plan_acceptance(self, ctx: RunContext, plan: TaskPlan) -> ValidationReport:
        checks: list[CheckResult] = []
        warnings: list[str] = []

        for item in plan.acceptance_checks:
            ctype = item.get("type")
            if ctype == "artifact_exists":
                key = item.get("key")
                prefix = item.get("key_prefix")
                if key:
                    path = ctx.state.artifacts.get(key)
                    ok = bool(path and Path(path).exists())
                    checks.append(CheckResult(f"artifact:{key}", ok, path or "missing"))
                elif prefix:
                    matched = {k: v for k, v in ctx.state.artifacts.items() if k.startswith(prefix) or prefix in k}
                    ok = any(Path(v).exists() for v in matched.values())
                    checks.append(CheckResult(f"artifact_prefix:{prefix}", ok, str(matched) if matched else "missing"))
            elif ctype == "metric_gte":
                name = item["name"]
                need = float(item["value"])
                got = ctx.state.metrics.get(name)
                # 若 score 非空率不存在，尝试 content
                if got is None and name.startswith("non_null_rate_"):
                    got = ctx.state.metrics.get("non_null_rate_content")
                ok = got is not None and float(got) >= need
                checks.append(CheckResult(f"metric_gte:{name}", ok, f"got={got}, need>={need}"))
            else:
                warnings.append(f"未知验收类型: {ctype}")

        # 通用：清洗后行数
        if "clean_data" in ctx.state.artifacts:
            rows = ctx.state.metrics.get("clean_row_count", 0)
            checks.append(CheckResult("clean_row_count>0", int(rows) > 0, str(rows)))

        passed = all(c.passed for c in checks) if checks else True
        return ValidationReport(passed=passed, checks=checks, warnings=warnings)
