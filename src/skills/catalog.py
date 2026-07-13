"""Skill catalog loader."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


def load_skill_catalog(skills_dir: str | Path | None = None) -> list[dict[str, Any]]:
    root = Path(skills_dir or Path(__file__).resolve().parent)
    skills: list[dict[str, Any]] = []
    for path in sorted(root.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        data["_path"] = str(path)
        skills.append(data)
    return skills
