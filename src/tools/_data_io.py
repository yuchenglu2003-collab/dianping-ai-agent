from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.data_resolver import load_table
from src.infra.schema_adapter import apply_schema_hints, rename_to_standard


def ensure_time_column(df: pd.DataFrame) -> pd.DataFrame:
    """统一时间列到 review_time（兼容行为日志 unix event_time）。"""
    if "review_time" in df.columns:
        return df
    out = df.copy()
    src = None
    if "event_time" in out.columns:
        src = out["event_time"]
    elif "time" in out.columns:
        src = out["time"]
    if src is None:
        return out

    num = pd.to_numeric(src, errors="coerce")
    if num.notna().mean() > 0.5 and float(num.dropna().median()) > 1e9:
        out["review_time"] = pd.to_datetime(num, unit="s", errors="coerce")
    else:
        out["review_time"] = pd.to_datetime(src, errors="coerce")
    return out


def load_analysis_frame(
    path: Path,
    *,
    schema_hints: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """读取分析用表，并按 schema_hints 映射为标准列名。"""
    df = load_table(path)
    mapped = apply_schema_hints(df, schema_hints or {})
    if mapped:
        df = rename_to_standard(df, mapped)
    return ensure_time_column(df)


def resolve_tool_input_path(ctx: Any, kwargs: dict[str, Any]) -> Path:
    """优先用工具参数 input，否则用清洗产物。"""
    raw = kwargs.get("input") or ctx.state.artifacts.get("clean_data") or ctx.state.artifacts.get("clean_csv")
    if not raw and ctx.data_inputs:
        raw = ctx.data_inputs[0]
    return Path(raw or "")
