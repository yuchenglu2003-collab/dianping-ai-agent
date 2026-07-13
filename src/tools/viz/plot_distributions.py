from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px

from src.tools._data_io import load_analysis_frame, resolve_tool_input_path
from src.tools.base import BaseTool, ToolResult
from src.tools.viz._plotly_io import save_plotly_figure


class PlotDistributionsTool(BaseTool):
    name = "plot_distributions"
    description = "绘制评分、门店等分布图"
    required_any_columns = [["score"], ["shop_id"]]

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        input_path = resolve_tool_input_path(ctx, kwargs)
        if not input_path.exists():
            return ToolResult(success=False, error=f"找不到清洗数据: {input_path}")

        df = load_analysis_frame(input_path, schema_hints=ctx.config.get("schema_hints"))
        outputs: dict[str, str] = {}
        metrics: dict[str, Any] = {}

        if "score" in df.columns:
            score = pd.to_numeric(df["score"], errors="coerce").dropna()
            if len(score):
                fig = px.histogram(score, nbins=10, title="评分分布")
                base = ctx.artifact_store.figure_path("score_distribution").with_suffix("")
                html, png = save_plotly_figure(fig, base)
                outputs["score_distribution"] = str(html)
                if png:
                    outputs["score_distribution_png"] = str(png)
                metrics["score_unique"] = int(score.nunique())

        if "shop_id" in df.columns:
            shop_counts = df["shop_id"].dropna().astype(str).value_counts().head(30).reset_index()
            shop_counts.columns = ["shop_id", "review_count"]
            if len(shop_counts):
                fig = px.bar(shop_counts, x="shop_id", y="review_count", title="门店评论量 Top30")
                base = ctx.artifact_store.figure_path("shop_review_count").with_suffix("")
                html, png = save_plotly_figure(fig, base)
                outputs["shop_review_count"] = str(html)
                if png:
                    outputs["shop_review_count_png"] = str(png)
                metrics["shop_count"] = int(df["shop_id"].nunique())

        if "content" in df.columns:
            lengths = df["content"].fillna("").astype(str).str.len()
            fig = px.histogram(lengths, nbins=40, title="评论长度分布")
            base = ctx.artifact_store.figure_path("content_length_distribution").with_suffix("")
            html, png = save_plotly_figure(fig, base)
            outputs["content_length_distribution"] = str(html)
            if png:
                outputs["content_length_distribution_png"] = str(png)
            metrics["content_len_mean"] = float(lengths.mean()) if len(lengths) else 0.0
            metrics["content_len_median"] = float(lengths.median()) if len(lengths) else 0.0

        ok = bool(outputs)
        cols = [str(c) for c in df.columns]
        return ToolResult(
            success=ok,
            outputs=outputs,
            metrics=metrics,
            message=f"生成 {len([k for k in outputs if not k.endswith('_png')])} 张分布图",
            error=None
            if ok
            else (
                "没有可绘制的字段（需要 score / shop_id / content 或其别名如 "
                f"cus_comment、rating）。当前列：{cols[:20]}"
            ),
        )
