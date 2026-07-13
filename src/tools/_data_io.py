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


def apply_column_mapping(df: pd.DataFrame, column_mapping: dict[str, str] | None) -> pd.DataFrame:
    """按 raw->std 映射重命名；已是标准名的列保持不变。"""
    if not column_mapping:
        return df
    rename = {raw: std for raw, std in column_mapping.items() if raw in df.columns and std not in df.columns}
    # 若清洗后已是标准名，也允许 identity
    if not rename:
        return df
    return rename_to_standard(df, rename)


def load_analysis_frame(
    path: Path,
    *,
    schema_hints: dict[str, list[str]] | None = None,
    column_mapping: dict[str, str] | None = None,
    nrows: int | None = None,
) -> pd.DataFrame:
    """读取分析用表：优先用 LLM/运行期 column_mapping，否则用 schema_hints。"""
    df = load_table(path, nrows=nrows) if nrows is not None else load_table(path)
    if column_mapping:
        df = apply_column_mapping(df, column_mapping)
    else:
        mapped = apply_schema_hints(df, schema_hints or {})
        if mapped:
            df = rename_to_standard(df, mapped)
    return ensure_time_column(df)


def mapping_from_ctx(ctx: Any) -> dict[str, str]:
    raw = ctx.extras.get("column_mapping") if getattr(ctx, "extras", None) else None
    return dict(raw) if isinstance(raw, dict) else {}


def load_analysis_frame_from_ctx(
    ctx: Any,
    path: Path | None = None,
    *,
    nrows: int | None = None,
) -> pd.DataFrame:
    p = path or resolve_tool_input_path(ctx, {})
    return load_analysis_frame(
        p,
        schema_hints=ctx.config.get("schema_hints"),
        column_mapping=mapping_from_ctx(ctx),
        nrows=nrows,
    )


def resolve_tool_input_path(ctx: Any, kwargs: dict[str, Any]) -> Path:
    """优先用工具参数 input，否则用清洗产物。"""
    raw = kwargs.get("input") or ctx.state.artifacts.get("clean_data") or ctx.state.artifacts.get("clean_csv")
    if not raw and ctx.data_inputs:
        raw = ctx.data_inputs[0]
    return Path(raw or "")
