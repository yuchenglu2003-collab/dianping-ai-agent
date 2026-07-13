from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class MetricStore:
    def __init__(self):
        self.metrics: dict[str, Any] = {}

    def update(self, values: dict[str, Any] | None) -> None:
        if values:
            self.metrics.update(values)

    def get(self, key: str, default: Any = None) -> Any:
        return self.metrics.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.metrics)

    def save(self, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.metrics, ensure_ascii=False, indent=2), encoding="utf-8")
