from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px

from src.tools._data_io import load_analysis_frame, resolve_tool_input_path
from src.tools.base import BaseTool, ToolResult
from src.tools.viz._plotly_io import save_plotly_figure


class EdaTimeseriesTool(BaseTool):
    name = "eda_timeseries"
    description = "时序趋势（评论量/均分，或销量/订单量）"
    required_columns = ["review_time"]

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        input_path = resolve_tool_input_path(ctx, kwargs)
        if not input_path.exists():
            return ToolResult(success=False, error=f"找不到清洗数据: {input_path}")

        df = load_analysis_frame(input_path, schema_hints=ctx.config.get("schema_hints"))
        if "review_time" not in df.columns:
            return ToolResult(
                success=False,
                error=(
                    "缺少时间字段（review_time / event_time / 成交时间 / time 等）。"
                    f"当前列：{list(df.columns)[:20]}"
                ),
            )

        df = df.copy()
        # 若仍是原始值（ensure 未转成 datetime），再转一次
        if not pd.api.types.is_datetime64_any_dtype(df["review_time"]):
            num = pd.to_numeric(df["review_time"], errors="coerce")
            if num.notna().mean() > 0.5 and num.dropna().median() > 1e9:
                df["review_time"] = pd.to_datetime(num, unit="s", errors="coerce")
            else:
                df["review_time"] = pd.to_datetime(df["review_time"], errors="coerce")
        df = df.dropna(subset=["review_time"])
        if df.empty:
            return ToolResult(success=False, error="有效时间字段为空")

        df["date"] = df["review_time"].dt.to_period("D").dt.to_timestamp()
        aggs: dict[str, tuple[str, str]] = {"event_count": ("review_time", "count")}
        if "score" in df.columns:
            aggs["score_mean"] = ("score", "mean")
        if "sales_qty" in df.columns:
            df["sales_qty"] = pd.to_numeric(df["sales_qty"], errors="coerce")
            aggs["sales_qty_sum"] = ("sales_qty", "sum")
        if "user_id" in df.columns:
            aggs["user_count"] = ("user_id", "nunique")
        if "shop_id" in df.columns:
            aggs["shop_count"] = ("shop_id", "nunique")
        if "order_id" in df.columns:
            aggs["order_count"] = ("order_id", "nunique")
        if "event_type" in df.columns:
            # 行为日志：额外统计购买事件
            buy = df["event_type"].astype(str).str.lower().isin(["buy", "order", "purchase", "购买"])
            df = df.assign(_buy=buy.astype(int))
            aggs["buy_count"] = ("_buy", "sum")

        daily = df.groupby("date").agg(**aggs).reset_index()

        outputs: dict[str, str] = {}
        if "sales_qty" in df.columns or "order_id" in df.columns:
            count_title = "每日销量/订单量趋势"
        elif "event_type" in df.columns:
            count_title = "每日行为事件量趋势"
        else:
            count_title = "每日评论量趋势"
        y_count = "sales_qty_sum" if "sales_qty_sum" in daily.columns else "event_count"
        fig = px.line(daily, x="date", y=y_count, title=count_title)
        base = ctx.artifact_store.figure_path("reviews_over_time").with_suffix("")
        html, png = save_plotly_figure(fig, base)
        outputs["reviews_over_time"] = str(html)
        if png:
            outputs["reviews_over_time_png"] = str(png)

        if "user_count" in daily.columns:
            fig_u = px.line(daily, x="date", y="user_count", title="每日 UV 趋势")
            base_u = ctx.artifact_store.figure_path("users_over_time").with_suffix("")
            html_u, png_u = save_plotly_figure(fig_u, base_u)
            outputs["users_over_time"] = str(html_u)
            if png_u:
                outputs["users_over_time_png"] = str(png_u)

        if "score_mean" in daily.columns:
            fig2 = px.line(daily, x="date", y="score_mean", title="每日均分趋势")
            base2 = ctx.artifact_store.figure_path("score_over_time").with_suffix("")
            html2, png2 = save_plotly_figure(fig2, base2)
            outputs["score_over_time"] = str(html2)
            if png2:
                outputs["score_over_time_png"] = str(png2)

        if "sales_qty_sum" in daily.columns and y_count != "sales_qty_sum":
            fig3 = px.line(daily, x="date", y="sales_qty_sum", title="每日销量合计趋势")
            base3 = ctx.artifact_store.figure_path("sales_over_time").with_suffix("")
            html3, png3 = save_plotly_figure(fig3, base3)
            outputs["sales_over_time"] = str(html3)
            if png3:
                outputs["sales_over_time_png"] = str(png3)

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
