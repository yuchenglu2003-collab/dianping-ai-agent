from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.data_resolver import load_table
from src.infra.schema_adapter import apply_schema_hints, rename_to_standard
from src.tools._data_io import apply_column_mapping, ensure_time_column, mapping_from_ctx
from src.tools.base import BaseTool, ToolResult


def normalize_score_series(series: pd.Series) -> pd.Series:
    """把评分列规范到约 1–5：支持数值、sml-str40、10/20/…/50 星级。"""
    if isinstance(series, pd.DataFrame):
        series = series.iloc[:, 0]
    raw = series
    num = pd.to_numeric(raw, errors="coerce")

    need = num.isna() & raw.notna()
    if bool(need.any()):
        extracted = raw.loc[need].astype(str).str.extract(r"(\d+(?:\.\d+)?)", expand=False)
        num.loc[need] = pd.to_numeric(extracted, errors="coerce")

    valid = num.dropna()
    if len(valid) > 0 and float(valid.between(10, 50).mean()) > 0.8:
        # 点评常见 10/20/30/40/50 → 1–5
        num = num / 10.0

    return num


class CleanTableTool(BaseTool):
    name = "clean_table"
    description = "去重、缺失与异常值清洗，输出干净数据集"
    required_any_columns = [
        ["score"],
        ["content"],
        ["shop_id"],
        ["sales_qty"],
        ["order_id"],
        ["user_id"],
        ["event_type"],
    ]

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        input_path = Path(kwargs.get("input") or ctx.data_inputs[0])
        # 云端禁用 parquet（pyarrow 易触发 segfault），只用 CSV
        df = load_table(input_path)
        raw_rows = len(df)

        col_map = mapping_from_ctx(ctx)
        if col_map:
            df = apply_column_mapping(df, col_map)
        else:
            mapped = apply_schema_hints(df, ctx.config.get("schema_hints", {}))
            df = rename_to_standard(df, mapped)
        df = ensure_time_column(df)

        params = ctx.params
        if params.get("drop_duplicates", True):
            df = self._drop_duplicates(df)

        rows_after_dedup = len(df)
        is_behavior = "event_type" in df.columns and "content" not in df.columns
        is_sales = "sales_qty" in df.columns or "order_id" in df.columns

        if "score" in df.columns and not is_behavior:
            df["score"] = normalize_score_series(df["score"])
            min_s = float(params.get("min_score", 1))
            max_s = float(params.get("max_score", 5))
            score_ok = df["score"].isna() | ((df["score"] >= min_s) & (df["score"] <= max_s))
            filtered = df[score_ok]
            # 若评分列映射错误导致全部被滤掉，跳过区间过滤，避免空表
            if len(filtered) == 0 and len(df) > 0:
                df = df.copy()
                df["score"] = pd.NA
            else:
                df = filtered

        if "content" in df.columns:
            df["content"] = df["content"].fillna("").astype(str).str.strip()
            # 纯数字/ID 误映射成 content 时不要全删：仅过滤空串
            min_len = int(params.get("min_text_len", 2))
            text_ok = df["content"].str.len() >= min_len
            # 若几乎全是空/过短，保留原表（可能是行为/销售表误带了 content）
            if float(text_ok.mean()) < 0.05 and len(df) > 0:
                pass
            else:
                df = df[text_ok]

        for num_col in ("sales_qty", "unit_price"):
            if num_col in df.columns:
                df[num_col] = pd.to_numeric(df[num_col], errors="coerce")

        if "review_time" in df.columns and not pd.api.types.is_datetime64_any_dtype(df["review_time"]):
            try:
                num = pd.to_numeric(df["review_time"], errors="coerce")
                if num.notna().mean() > 0.5 and float(num.dropna().median()) > 1e9:
                    df["review_time"] = pd.to_datetime(num, unit="s", errors="coerce")
                else:
                    df["review_time"] = pd.to_datetime(df["review_time"], errors="coerce", utc=False)
            except Exception:
                pass

        # 按场景选择去空键；不可用的 score（几乎全空）不参与 dropna
        key_cols: list[str] = []
        if is_behavior:
            key_cols = [c for c in ["user_id", "event_type"] if c in df.columns][:1]
        elif is_sales and "content" not in df.columns:
            key_cols = [c for c in ["sales_qty", "order_id", "shop_id"] if c in df.columns][:1]
        else:
            if "content" in df.columns:
                # content 已转成字符串，用长度过滤即可，不再 dropna
                pass
            if "score" in df.columns and float(df["score"].notna().mean()) >= 0.1:
                key_cols.append("score")
            if not key_cols:
                key_cols = [c for c in ["sales_qty", "order_id", "shop_id", "user_id"] if c in df.columns][:1]

        before_na = len(df)
        if key_cols:
            cleaned = df.dropna(subset=key_cols)
            # 保底：dropna 若清空整表，回退为不过滤
            if len(cleaned) == 0 and before_na > 0:
                cleaned = df
            df = cleaned

        out_dir = Path(ctx.paths.get("clean", ctx.project_root / "data" / "clean"))
        out_dir.mkdir(parents=True, exist_ok=True)
        # 文件名只用 ASCII，避免中文 task_id 在部分环境异常
        safe_name = "".join(
            ch if ch.isascii() and (ch.isalnum() or ch in "-_") else "_"
            for ch in str(ctx.task.task_id)
        )
        safe_name = "_".join(p for p in safe_name.split("_") if p)[:40] or "task"
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
        if "score" in df.columns and len(df) and df["score"].notna().any():
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
        """按评论/订单粒度去重。"""
        if "order_id" in df.columns:
            return df.drop_duplicates(subset=["order_id"], keep="first")
        if "review_id" in df.columns:
            return df.drop_duplicates(subset=["review_id"], keep="first")

        candidates = [
            ["user_id", "shop_id", "review_time", "content"],
            ["user_id", "shop_id", "review_time"],
            ["user_id", "content", "review_time"],
            ["content", "review_time", "shop_id"],
            ["shop_id", "product_id", "review_time", "sales_qty"],
            ["user_id", "product_id", "event_time", "event_type"],
        ]
        for subset in candidates:
            cols = [c for c in subset if c in df.columns]
            if len(cols) >= 3:
                return df.drop_duplicates(subset=cols, keep="first")

        return df
