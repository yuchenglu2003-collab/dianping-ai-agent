from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from src.task_spec import TaskSpec


def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[:64] or "task"


def _parse_markdown(path: Path, text: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            front = yaml.safe_load(parts[1]) or {}
            if isinstance(front, dict):
                data.update(front)
            text = parts[2]

    title_match = re.search(r"^#\s+任务[:：]?\s*(.+)$", text, re.M)
    if title_match and "task_id" not in data:
        data["goal"] = data.get("goal") or title_match.group(1).strip()
        data["task_id"] = _slugify(title_match.group(1))

    def section(name: str) -> str:
        pattern = rf"^##\s+{name}\s*$([\s\S]*?)(?=^##\s+|\Z)"
        m = re.search(pattern, text, re.M)
        return m.group(1).strip() if m else ""

    if "goal" not in data:
        goal_body = section("目标")
        if goal_body:
            data["goal"] = goal_body.split("\n")[0].strip("- ").strip()

    if "deliverables" not in data:
        deliverables: list[str] = []
        body = section("期望产出") or section("产出")
        for line in body.splitlines():
            line = line.strip()
            if re.match(r"^[-*\d.]+", line):
                deliverables.append(re.sub(r"^[-*\d.]+\s*", "", line))
        if deliverables:
            data["deliverables"] = deliverables

    if "acceptance" not in data:
        acceptance: dict[str, Any] = {}
        body = section("验收标准") or section("验收")
        for line in body.splitlines():
            line = line.strip("- ").strip()
            if not line:
                continue
            if "非空率" in line and ">=" in line:
                m = re.search(r">=\s*([\d.]+)%?", line)
                if m:
                    val = float(m.group(1))
                    acceptance["min_non_null_rate"] = val / 100 if val > 1 else val
            elif "图表" in line:
                acceptance["figures_required"] = True
            else:
                acceptance.setdefault("notes", []).append(line)
        if acceptance:
            data["acceptance"] = acceptance

    if "params" not in data:
        params: dict[str, Any] = {}
        body = section("口径") or section("口径（可选）")
        for line in body.splitlines():
            line = line.strip("- ").strip()
            if "好评" in line and ">=" in line:
                m = re.search(r">=\s*([\d.]+)", line)
                if m:
                    params["positive_threshold"] = float(m.group(1))
            if "时间字段" in line:
                m = re.search(r"[:：]\s*(\w+)", line)
                if m:
                    params["time_col"] = m.group(1)
        if params:
            data["params"] = params

    data.setdefault("task_id", _slugify(path.stem))
    data.setdefault("goal", data.get("goal") or path.stem)
    data["_raw_text"] = text
    return data


def load_task(path: str | Path) -> TaskSpec:
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"任务文件不存在: {path}")

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        payload = yaml.safe_load(text) or {}
        if not isinstance(payload, dict):
            raise ValueError("YAML 任务文件必须是 mapping")
        payload["_raw_text"] = text
    else:
        payload = _parse_markdown(path, text)

    raw_text = payload.pop("_raw_text", text)
    return TaskSpec(
        task_id=str(payload.get("task_id") or path.stem),
        goal=str(payload.get("goal") or ""),
        data=list(payload.get("data") or []),
        deliverables=list(payload.get("deliverables") or []),
        acceptance=dict(payload.get("acceptance") or {}),
        params=dict(payload.get("params") or {}),
        needs_human_review=bool(payload.get("needs_human_review", False)),
        report=dict(payload.get("report") or {}),
        raw_path=str(path),
        raw_text=raw_text,
    )
