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
    if suffix in {".csv", ".tsv"}:
        return _read_delimited(path, nrows=nrows, force_tab=(suffix == ".tsv"))
    if suffix == ".parquet":
        try:
            df = pd.read_parquet(path)
        except Exception as e:
            raise RuntimeError(f"读取 parquet 失败（可改用 CSV）: {e}") from e
        return df.head(nrows) if nrows else df
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, nrows=nrows)
    raise ValueError(f"不支持的文件类型: {suffix}")


def _detect_sep(sample: str) -> str:
    return "\t" if sample.count("\t") > sample.count(",") else ","


def _read_delimited(path: Path, *, nrows: int | None, force_tab: bool = False) -> pd.DataFrame:
    last_err: Exception | None = None
    for enc in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            with open(path, "r", encoding=enc, errors="strict") as f:
                header = f.readline()
            sep = "\t" if force_tab else _detect_sep(header)
            df = pd.read_csv(
                path,
                sep=sep,
                nrows=nrows,
                encoding=enc,
                on_bad_lines="skip",
                low_memory=False,
            )
            # 行为日志可能被误读成单列，再按 tab 重试
            if df.shape[1] == 1 and "\t" in str(df.columns[0]):
                df = pd.read_csv(
                    path,
                    sep="\t",
                    nrows=nrows,
                    encoding=enc,
                    on_bad_lines="skip",
                    low_memory=False,
                )
            return df
        except Exception as e:
            last_err = e
    raise RuntimeError(f"读取表格失败: {path} | {last_err}")


def profile_table(path: Path, schema_hints: dict[str, list[str]] | None = None, sample_n: int = 3) -> TableSummary:
    # 超大行为日志只抽样探查，避免云端 OOM
    try:
        size_mb = path.stat().st_size / (1024 * 1024)
    except OSError:
        size_mb = 0
    nrows = 50000 if size_mb > 10 else None
    df = load_table(path, nrows=nrows)
    mapped = apply_schema_hints(df, schema_hints or {})
    null_rates = {c: float(df[c].isna().mean()) for c in df.columns}
    sample = df.head(sample_n).astype(object).where(pd.notnull(df.head(sample_n)), None)
    # 若抽样，行数用文件粗估
    rows = int(len(df))
    if nrows is not None:
        try:
            with open(path, "rb") as f:
                rows = max(sum(1 for _ in f) - 1, rows)
        except OSError:
            pass
    return TableSummary(
        path=str(path),
        rows=rows,
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
