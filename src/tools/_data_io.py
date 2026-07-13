from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.data_resolver import load_table
from src.infra.schema_adapter import apply_schema_hints, rename_to_standard


def load_analysis_frame(
    path: Path,
    *,
    schema_hints: dict[str, list[str]] | None = None,
) -> pd.DataFrame:
    """读取分析用表，并按 schema_hints 映射为标准列名。

    云端 LLM 规划有时会把原始上传文件直接传给绘图工具；
    若不做映射，会因只有 cus_comment 等原始列而报「没有可绘制的字段」。
    """
    df = load_table(path)
    mapped = apply_schema_hints(df, schema_hints or {})
    if mapped:
        df = rename_to_standard(df, mapped)
    return df


def resolve_tool_input_path(ctx: Any, kwargs: dict[str, Any]) -> Path:
    """优先用工具参数 input，否则用清洗产物。"""
    raw = kwargs.get("input") or ctx.state.artifacts.get("clean_data") or ctx.state.artifacts.get("clean_csv")
    if not raw and ctx.data_inputs:
        raw = ctx.data_inputs[0]
    return Path(raw or "")
