from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px

from src.tools.base import BaseTool, ToolResult
from src.tools.viz._plotly_io import save_plotly_figure


class PlotDistributionsTool(BaseTool):
    name = "plot_distributions"
    description = "绘制评分、门店等分布图"
    required_any_columns = [["score"], ["shop_id"]]

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        input_path = Path(kwargs.get("input") or ctx.state.artifacts.get("clean_data") or "")
        if not input_path.exists():
            return ToolResult(success=False, error=f"找不到清洗数据: {input_path}")

        df = pd.read_parquet(input_path) if input_path.suffix == ".parquet" else pd.read_csv(input_path)
        outputs: dict[str, str] = {}
        metrics: dict[str, Any] = {}

        if "score" in df.columns:
            fig = px.histogram(df, x="score", nbins=10, title="评分分布")
            base = ctx.artifact_store.figure_path("score_distribution").with_suffix("")
            html, png = save_plotly_figure(fig, base)
            outputs["score_distribution"] = str(html)
            if png:
                outputs["score_distribution_png"] = str(png)
            metrics["score_unique"] = int(df["score"].nunique())

        if "shop_id" in df.columns:
            shop_counts = df["shop_id"].value_counts().head(30).reset_index()
            shop_counts.columns = ["shop_id", "review_count"]
            fig = px.bar(shop_counts, x="shop_id", y="review_count", title="门店评论量 Top30")
            base = ctx.artifact_store.figure_path("shop_review_count").with_suffix("")
            html, png = save_plotly_figure(fig, base)
            outputs["shop_review_count"] = str(html)
            if png:
                outputs["shop_review_count_png"] = str(png)
            metrics["shop_count"] = int(df["shop_id"].nunique())

        if "content" in df.columns:
            lengths = df["content"].astype(str).str.len()
            fig = px.histogram(lengths, nbins=40, title="评论长度分布")
            base = ctx.artifact_store.figure_path("content_length_distribution").with_suffix("")
            html, png = save_plotly_figure(fig, base)
            outputs["content_length_distribution"] = str(html)
            if png:
                outputs["content_length_distribution_png"] = str(png)
            metrics["content_len_mean"] = float(lengths.mean())
            metrics["content_len_median"] = float(lengths.median())

        ok = bool(outputs)
        return ToolResult(
            success=ok,
            outputs=outputs,
            metrics=metrics,
            message=f"生成 {len([k for k in outputs if not k.endswith('_png')])} 张分布图",
            error=None if ok else "没有可绘制的字段",
        )
