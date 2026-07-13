from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px

from src.tools._data_io import load_analysis_frame, resolve_tool_input_path
from src.tools.base import BaseTool, ToolResult
from src.tools.viz._plotly_io import save_plotly_figure


class EdaTimeseriesTool(BaseTool):
    name = "eda_timeseries"
    description = "评论量、评分、用户量时序趋势"
    required_columns = ["review_time"]

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        input_path = resolve_tool_input_path(ctx, kwargs)
        if not input_path.exists():
            return ToolResult(success=False, error=f"找不到清洗数据: {input_path}")

        df = load_analysis_frame(input_path, schema_hints=ctx.config.get("schema_hints"))
        if "review_time" not in df.columns:
            return ToolResult(
                success=False,
                error=f"缺少 review_time 字段（或 comment_time 等别名）。当前列：{list(df.columns)[:20]}",
            )

        df = df.copy()
        df["review_time"] = pd.to_datetime(df["review_time"], errors="coerce")
        df = df.dropna(subset=["review_time"])
        if df.empty:
            return ToolResult(success=False, error="有效时间字段为空")

        df["date"] = df["review_time"].dt.to_period("D").dt.to_timestamp()
        daily = df.groupby("date").agg(
            review_count=("review_time", "count"),
            score_mean=("score", "mean") if "score" in df.columns else ("review_time", "count"),
            user_count=("user_id", "nunique") if "user_id" in df.columns else ("review_time", "count"),
            shop_count=("shop_id", "nunique") if "shop_id" in df.columns else ("review_time", "count"),
        ).reset_index()

        outputs: dict[str, str] = {}
        fig = px.line(daily, x="date", y="review_count", title="每日评论量趋势")
        base = ctx.artifact_store.figure_path("reviews_over_time").with_suffix("")
        html, png = save_plotly_figure(fig, base)
        outputs["reviews_over_time"] = str(html)
        if png:
            outputs["reviews_over_time_png"] = str(png)

        if "score" in df.columns:
            fig2 = px.line(daily, x="date", y="score_mean", title="每日均分趋势")
            base2 = ctx.artifact_store.figure_path("score_over_time").with_suffix("")
            html2, png2 = save_plotly_figure(fig2, base2)
            outputs["score_over_time"] = str(html2)
            if png2:
                outputs["score_over_time_png"] = str(png2)

        return ToolResult(
            success=True,
            outputs=outputs,
            metrics={
                "timeseries_days": int(daily["date"].nunique()),
                "timeseries_start": str(daily["date"].min().date()),
                "timeseries_end": str(daily["date"].max().date()),
            },
            message="时序分析完成",
        )
