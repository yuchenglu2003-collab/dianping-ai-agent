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
            df = df[df["score"].between(min_s, max_s) | df["score"].isna()]

        if "content" in df.columns:
            df["content"] = df["content"].astype(str).fillna("").str.strip()
            min_len = int(params.get("min_text_len", 2))
            df = df[df["content"].str.len() >= min_len]

        if "review_time" in df.columns:
            df["review_time"] = pd.to_datetime(df["review_time"], errors="coerce")

        # 关键字段缺失处理：评论文本/评分为空则丢弃（可配置）
        key_cols = [c for c in ["score", "content"] if c in df.columns]
        before_na = len(df)
        if key_cols:
            df = df.dropna(subset=key_cols)

        out_dir = Path(ctx.paths.get("clean", ctx.project_root / "data" / "clean"))
        out_dir.mkdir(parents=True, exist_ok=True)
        csv_path = out_dir / f"{ctx.task.task_id}_clean.csv"
        df.to_csv(csv_path, index=False)
        out_path = csv_path
        try:
            parquet_path = out_dir / f"{ctx.task.task_id}_clean.parquet"
            df.to_parquet(parquet_path, index=False)
            out_path = parquet_path
        except Exception:
            parquet_path = None


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
            outputs={"clean_data": str(out_path), "clean_csv": str(csv_path)},
            metrics=metrics,
            message=f"清洗完成: {raw_rows} -> {len(df)}",
            error=None if len(df) > 0 else "清洗后数据为空",
        )

    def _drop_duplicates(self, df: pd.DataFrame) -> pd.DataFrame:
        """按评论粒度去重，避免仅 shop_id 去重误删大量数据。"""
        if "review_id" in df.columns:
            return df.drop_duplicates(subset=["review_id"])

        candidates = [
            ["user_id", "shop_id", "review_time", "content"],
            ["user_id", "shop_id", "review_time"],
            ["user_id", "content", "review_time"],
            ["content", "review_time", "shop_id"],
        ]
        for subset in candidates:
            cols = [c for c in subset if c in df.columns]
            if len(cols) >= 3:
                return df.drop_duplicates(subset=cols)

        # 无法构成合理主键时不去重
        return df
