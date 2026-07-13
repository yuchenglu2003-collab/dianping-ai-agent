from __future__ import annotations

from pathlib import Path
from typing import Any


def apply_schema_hints(df, schema_hints: dict[str, list[str]]) -> dict[str, str]:
    """返回 原始列名 -> 标准列名 的映射（仅命中的列）。"""
    lower_map = {str(c).lower(): str(c) for c in df.columns}
    mapped: dict[str, str] = {}
    used_std: set[str] = set()

    for std_name, aliases in (schema_hints or {}).items():
        candidates = [std_name, *(aliases or [])]
        for alias in candidates:
            src = lower_map.get(str(alias).lower())
            if src and std_name not in used_std:
                mapped[src] = std_name
                used_std.add(std_name)
                break
    return mapped


def rename_to_standard(df, mapped: dict[str, str]):
    return df.rename(columns=mapped)


def infer_table_kind(mapped: dict[str, str]) -> str:
    standards = set(mapped.values())
    if {"score", "content"} & standards or {"review_time", "content"} <= standards:
        return "reviews"
    if {"sales_qty", "date"} <= standards or "sales_qty" in standards:
        return "sales"
    if {"event_type", "event_time"} <= standards or "event_type" in standards:
        return "events"
    if "shop_name" in standards or ({"shop_id"} <= standards and "score" not in standards):
        return "shops"
    return "unknown"


def resolve_column(columns: list[str], mapped: dict[str, str], logical: str) -> str | None:
    # mapped: raw -> standard
    for raw, std in mapped.items():
        if std == logical:
            return raw if raw in columns else std
    if logical in columns:
        return logical
    return None
