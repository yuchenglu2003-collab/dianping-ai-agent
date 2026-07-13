from __future__ import annotations

from pathlib import Path


def load_prompt(name: str) -> str:
    path = Path(__file__).resolve().parent / name
    if not path.exists():
        raise FileNotFoundError(f"Prompt 不存在: {path}")
    return path.read_text(encoding="utf-8").strip()
