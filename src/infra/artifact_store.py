from __future__ import annotations

from pathlib import Path


class ArtifactStore:
    def __init__(self, root: str | Path, task_id: str, run_id: str):
        self.root = Path(root)
        self.task_id = task_id
        self.run_id = run_id
        for sub in ("figures", "models", "reports", "metrics"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)

    def figure_path(self, name: str, ext: str = "html") -> Path:
        return self.root / "figures" / f"{self.task_id}_{name}.{ext}"

    def model_path(self, model_name: str, ext: str = "joblib") -> Path:
        return self.root / "models" / f"{self.task_id}_{model_name}_{self.run_id}.{ext}"

    def report_path(self, name: str, ext: str = "md") -> Path:
        return self.root / "reports" / f"{self.task_id}_{name}.{ext}"

    def metrics_path(self) -> Path:
        return self.root / "metrics" / f"{self.task_id}_metrics.json"
