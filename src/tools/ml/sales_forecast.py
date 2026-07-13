from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import plotly.express as px

from src.tools._data_io import load_analysis_frame, resolve_tool_input_path
from src.tools.base import BaseTool, ToolResult
from src.tools.viz._plotly_io import save_plotly_figure


class SalesForecastTool(BaseTool):
    name = "sales_forecast"
    description = "门店销量时序、简单预测与异常检测"

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        input_path = resolve_tool_input_path(ctx, kwargs)
        if not input_path.exists():
            return ToolResult(success=False, error=f"找不到数据: {input_path}")

        df = load_analysis_frame(input_path, schema_hints=ctx.config.get("schema_hints"))
        if "sales_qty" not in df.columns:
            return ToolResult(success=False, error=f"销量预测需要 sales_qty/销量。当前列：{list(df.columns)[:20]}")
        if "review_time" not in df.columns:
            return ToolResult(success=False, error="销量预测需要成交时间")

        work = df.copy()
        work["sales_qty"] = pd.to_numeric(work["sales_qty"], errors="coerce")
        work["unit_price"] = pd.to_numeric(work.get("unit_price", np.nan), errors="coerce")
        work["review_time"] = pd.to_datetime(work["review_time"], errors="coerce")
        work = work.dropna(subset=["sales_qty", "review_time"])
        work["date"] = work["review_time"].dt.to_period("D").dt.to_timestamp()
        work["gmv"] = work["sales_qty"] * work["unit_price"].fillna(0)

        daily = work.groupby("date", as_index=False).agg(sales_qty=("sales_qty", "sum"), gmv=("gmv", "sum"), orders=("sales_qty", "count"))
        daily = daily.sort_values("date")

        # 简单移动平均预测
        horizon = int(ctx.params.get("forecast_horizon_days", ctx.config.get("defaults", {}).get("forecast_horizon_days", 14)))
        window = min(7, max(3, len(daily) // 5)) if len(daily) >= 3 else 1
        daily["ma"] = daily["sales_qty"].rolling(window=window, min_periods=1).mean()
        last_ma = float(daily["ma"].iloc[-1]) if len(daily) else 0.0
        last_date = daily["date"].iloc[-1] if len(daily) else pd.Timestamp.today()
        future = pd.DataFrame(
            {
                "date": pd.date_range(last_date + pd.Timedelta(days=1), periods=horizon, freq="D"),
                "sales_qty": [last_ma] * horizon,
                "type": ["forecast"] * horizon,
            }
        )
        hist = daily[["date", "sales_qty"]].assign(type="actual")
        plot_df = pd.concat([hist, future], ignore_index=True)
        fig = px.line(plot_df, x="date", y="sales_qty", color="type", title="销量实际 vs 简易预测")
        base = ctx.artifact_store.figure_path("sales_forecast").with_suffix("")
        html, png = save_plotly_figure(fig, base)

        # IQR 异常：销量与单价
        outputs: dict[str, str] = {"sales_forecast": str(html)}
        if png:
            outputs["sales_forecast_png"] = str(png)

        def _iqr_flags(s: pd.Series) -> pd.Series:
            q1, q3 = s.quantile(0.25), s.quantile(0.75)
            iqr = q3 - q1
            lo, hi = q1 - 1.5 * iqr, q3 + 1.5 * iqr
            return (s < lo) | (s > hi)

        anom_sales = int(_iqr_flags(work["sales_qty"]).sum())
        anom_price = int(_iqr_flags(work["unit_price"].dropna()).sum()) if work["unit_price"].notna().any() else 0

        # 门店对比
        if "shop_id" in work.columns:
            shop = (
                work.groupby(work["shop_id"].astype(str), as_index=False)["sales_qty"]
                .sum()
                .sort_values("sales_qty", ascending=False)
                .head(20)
            )
            fig2 = px.bar(shop, x="shop_id", y="sales_qty", title="门店销量 Top20")
            base2 = ctx.artifact_store.figure_path("shop_sales_top").with_suffix("")
            html2, png2 = save_plotly_figure(fig2, base2)
            outputs["shop_sales_top"] = str(html2)
            if png2:
                outputs["shop_sales_top_png"] = str(png2)

        # 季度/月份
        work["month"] = work["review_time"].dt.to_period("M").astype(str)
        monthly = work.groupby("month", as_index=False)["sales_qty"].sum()
        fig3 = px.bar(monthly, x="month", y="sales_qty", title="月度销量")
        base3 = ctx.artifact_store.figure_path("sales_monthly").with_suffix("")
        html3, png3 = save_plotly_figure(fig3, base3)
        outputs["sales_monthly"] = str(html3)
        if png3:
            outputs["sales_monthly_png"] = str(png3)

        report = ctx.artifact_store.report_path("sales_forecast")
        lines = [
            "# 门店销量预测与异常监控",
            "",
            f"- 历史天数: {len(daily)}",
            f"- 预测天数: {horizon}",
            f"- 预测基准(近期均量): {last_ma:.3f}",
            f"- 销量异常点数(IQR): {anom_sales}",
            f"- 单价异常点数(IQR): {anom_price}",
            f"- 总销量: {float(work['sales_qty'].sum()):.3f}",
            f"- 总GMV: {float(work['gmv'].sum()):.3f}",
        ]
        report.write_text("\n".join(lines), encoding="utf-8")
        outputs["sales_forecast_report"] = str(report)

        metrics = {
            "sales_days": int(len(daily)),
            "sales_forecast_horizon": horizon,
            "sales_forecast_ma": last_ma,
            "sales_anomaly_count": anom_sales,
            "price_anomaly_count": anom_price,
            "sales_total": float(work["sales_qty"].sum()),
            "gmv_total": float(work["gmv"].sum()),
        }
        return ToolResult(success=True, outputs=outputs, metrics=metrics, message="销量预测与异常检测完成")
