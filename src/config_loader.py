from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(path: str | Path | None = None, project_root: Path | None = None) -> dict[str, Any]:
    root = project_root or Path.cwd()
    load_dotenv(root / ".env", override=False)
    config_path = Path(path) if path else root / "config" / "config.yaml"
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    with config_path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}

    paths = cfg.setdefault("paths", {})
    for key, value in list(paths.items()):
        p = Path(value)
        if not p.is_absolute():
            paths[key] = str((root / p).resolve())
    return cfg
