from __future__ import annotations

from datetime import datetime
from pathlib import Path

from src.ui.task_builder import build_task_from_text, infer_deliverables_from_text


def save_uploaded_files(uploaded_files, upload_root: Path) -> list[Path]:
    if not uploaded_files:
        return []
    session_dir = upload_root / datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for f in uploaded_files:
        dest = session_dir / f.name
        dest.write_bytes(f.getbuffer())
        saved.append(dest)
    return saved


__all__ = [
    "save_uploaded_files",
    "build_task_from_text",
    "infer_deliverables_from_text",
]
