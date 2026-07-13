from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.data_resolver import load_table
from src.infra.schema_adapter import apply_schema_hints, rename_to_standard
from src.tools.base import BaseTool, ToolResult


class CleanTableTool(BaseTool):
    name = "clean_table"
    description = "去重、缺失与异常值清洗，输出干净数据集"
    required_any_columns = [["score"], ["content"], ["shop_id"]]

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        input_path = Path(kwargs.get("input") or ctx.data_inputs[0])
        # 云端禁用 parquet（pyarrow 易触发 segfault），只用 CSV
        df = load_table(input_path)
        raw_rows = len(df)

        mapped = apply_schema_hints(df, ctx.config.get("schema_hints", {}))
        df = rename_to_standard(df, mapped)

        params = ctx.params
        if params.get("drop_duplicates", True):
            df = self._drop_duplicates(df)

        rows_after_dedup = len(df)

        if "score" in df.columns:
            df["score"] = pd.to_numeric(df["score"], errors="coerce")
            min_s = float(params.get("min_score", 1))
            max_s = float(params.get("max_score", 5))
            df = df[(df["score"].isna()) | ((df["score"] >= min_s) & (df["score"] <= max_s))]

        if "content" in df.columns:
            df["content"] = df["content"].fillna("").astype(str).str.strip()
            min_len = int(params.get("min_text_len", 2))
            df = df[df["content"].str.len() >= min_len]

        if "review_time" in df.columns:
            # 不用 format='mixed' 的重路径；失败则置空，避免底层崩溃
            try:
                df["review_time"] = pd.to_datetime(df["review_time"], errors="coerce", utc=False)
            except Exception:
                df["review_time"] = pd.NaT

        key_cols = [c for c in ["score", "content"] if c in df.columns]
        before_na = len(df)
        if key_cols:
            df = df.dropna(subset=key_cols)

        out_dir = Path(ctx.paths.get("clean", ctx.project_root / "data" / "clean"))
        out_dir.mkdir(parents=True, exist_ok=True)
        # 文件名只用 ASCII，避免中文 task_id 在部分环境异常
        safe_name = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(ctx.task.task_id))[:40] or "task"
        csv_path = out_dir / f"{safe_name}_{ctx.run_id}_clean.csv"
        df.to_csv(csv_path, index=False, encoding="utf-8")

        non_null_rates = {}
        for c in key_cols:
            non_null_rates[c] = float(df[c].notna().mean()) if len(df) else 0.0

        metrics = {
            "raw_rows": raw_rows,
            "clean_row_count": int(len(df)),
            "dropped_rows": int(raw_rows - len(df)),
            "dropped_after_dedup": int(raw_rows - rows_after_dedup),
            "dropped_na_rows": int(before_na - len(df)),
            **{f"non_null_rate_{k}": v for k, v in non_null_rates.items()},
        }
        if "score" in df.columns and len(df):
            metrics["score_mean"] = float(df["score"].mean())
            metrics["score_std"] = float(df["score"].std(ddof=0) or 0)

        return ToolResult(
            success=len(df) > 0,
            outputs={
                "clean_data": str(csv_path),
                "clean_csv": str(csv_path),
                "clean_data_download": str(csv_path),
            },
            metrics=metrics,
            message=f"清洗完成: {raw_rows} -> {len(df)}",
            error=None if len(df) > 0 else "清洗后数据为空",
        )

    def _drop_duplicates(self, df: pd.DataFrame) -> pd.DataFrame:
        """按评论粒度去重，避免仅 shop_id 去重误删大量数据。"""
        if "review_id" in df.columns:
            return df.drop_duplicates(subset=["review_id"], keep="first")

        candidates = [
            ["user_id", "shop_id", "review_time", "content"],
            ["user_id", "shop_id", "review_time"],
            ["user_id", "content", "review_time"],
            ["content", "review_time", "shop_id"],
        ]
        for subset in candidates:
            cols = [c for c in subset if c in df.columns]
            if len(cols) >= 3:
                return df.drop_duplicates(subset=cols, keep="first")

        return df
