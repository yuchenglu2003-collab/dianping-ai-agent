from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from src.infra.schema_adapter import apply_schema_hints, infer_table_kind


SUPPORTED_SUFFIXES = {".csv", ".tsv", ".parquet", ".xlsx", ".xls"}


@dataclass
class TableSummary:
    path: str
    rows: int
    columns: list[str]
    dtypes: dict[str, str]
    null_rates: dict[str, float]
    sample_rows: list[dict[str, Any]] = field(default_factory=list)
    mapped_columns: dict[str, str] = field(default_factory=dict)
    table_kind: str = "unknown"

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "rows": self.rows,
            "columns": self.columns,
            "dtypes": self.dtypes,
            "null_rates": self.null_rates,
            "sample_rows": self.sample_rows,
            "mapped_columns": self.mapped_columns,
            "table_kind": self.table_kind,
        }


@dataclass
class SchemaSummary:
    tables: list[TableSummary] = field(default_factory=list)

    @property
    def all_columns(self) -> set[str]:
        cols: set[str] = set()
        for t in self.tables:
            cols.update(t.columns)
            cols.update(t.mapped_columns.values())
        return cols

    def primary(self) -> TableSummary | None:
        return self.tables[0] if self.tables else None

    def to_dict(self) -> dict[str, Any]:
        return {"tables": [t.to_dict() for t in self.tables]}


def resolve_data_paths(data: str | Path | list[str | Path] | None, task_data: list[dict] | None = None) -> list[Path]:
    paths: list[Path] = []
    if data is not None:
        items = data if isinstance(data, list) else [data]
        for item in items:
            p = Path(item).expanduser().resolve()
            if p.is_dir():
                for child in sorted(p.iterdir()):
                    if child.suffix.lower() in SUPPORTED_SUFFIXES and child.is_file():
                        paths.append(child)
            elif p.is_file():
                paths.append(p)
            else:
                raise FileNotFoundError(f"数据路径不存在: {p}")

    for item in task_data or []:
        p = Path(item["path"]).expanduser().resolve()
        if p.exists() and p not in paths:
            paths.append(p)

    if not paths:
        raise ValueError("未找到可用数据文件，请通过 --data 或任务文件 data 字段指定")
    return paths


def load_table(path: Path, nrows: int | None = None) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, nrows=nrows)
    if suffix == ".tsv":
        return pd.read_csv(path, sep="\t", nrows=nrows)
    if suffix == ".parquet":
        df = pd.read_parquet(path)
        return df.head(nrows) if nrows else df
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, nrows=nrows)
    raise ValueError(f"不支持的文件类型: {suffix}")


def profile_table(path: Path, schema_hints: dict[str, list[str]] | None = None, sample_n: int = 3) -> TableSummary:
    df = load_table(path)
    mapped = apply_schema_hints(df, schema_hints or {})
    null_rates = {c: float(df[c].isna().mean()) for c in df.columns}
    sample = df.head(sample_n).astype(object).where(pd.notnull(df.head(sample_n)), None)
    return TableSummary(
        path=str(path),
        rows=int(len(df)),
        columns=[str(c) for c in df.columns],
        dtypes={str(c): str(t) for c, t in df.dtypes.items()},
        null_rates=null_rates,
        sample_rows=sample.to_dict(orient="records"),
        mapped_columns=mapped,
        table_kind=infer_table_kind(mapped),
    )


def build_schema_summary(
    paths: list[Path],
    schema_hints: dict[str, list[str]] | None = None,
) -> SchemaSummary:
    return SchemaSummary(tables=[profile_table(p, schema_hints) for p in paths])
