from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px

from src.tools._data_io import load_analysis_frame, resolve_tool_input_path
from src.tools.base import BaseTool, ToolResult
from src.tools.viz._plotly_io import save_plotly_figure


class PlotDistributionsTool(BaseTool):
    name = "plot_distributions"
    description = "绘制分布图（评论评分/门店，或销量/单价/商品等）"
    required_any_columns = [["score"], ["shop_id"], ["sales_qty"], ["unit_price"], ["product_id"]]

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        input_path = resolve_tool_input_path(ctx, kwargs)
        if not input_path.exists():
            return ToolResult(success=False, error=f"找不到清洗数据: {input_path}")

        df = load_analysis_frame(input_path, schema_hints=ctx.config.get("schema_hints"))
        outputs: dict[str, str] = {}
        metrics: dict[str, Any] = {}

        def _hist(series: pd.Series, name: str, title: str, nbins: int = 20) -> None:
            s = pd.to_numeric(series, errors="coerce").dropna()
            if s.empty:
                return
            fig = px.histogram(s, nbins=nbins, title=title)
            base = ctx.artifact_store.figure_path(name).with_suffix("")
            html, png = save_plotly_figure(fig, base)
            outputs[name] = str(html)
            if png:
                outputs[f"{name}_png"] = str(png)
            metrics[f"{name}_mean"] = float(s.mean())
            metrics[f"{name}_median"] = float(s.median())

        def _topk_bar(series: pd.Series, name: str, title: str, value_name: str = "count") -> None:
            counts = (
                series.dropna()
                .astype(str)
                .value_counts()
                .head(30)
                .rename_axis("label")
                .reset_index(name=value_name)
            )
            if counts.empty or len(counts.columns) < 2:
                return
            fig = px.bar(counts, x="label", y=value_name, title=title)
            base = ctx.artifact_store.figure_path(name).with_suffix("")
            html, png = save_plotly_figure(fig, base)
            outputs[name] = str(html)
            if png:
                outputs[f"{name}_png"] = str(png)
            metrics[f"{name}_unique"] = int(series.nunique())

        # ---- 评论场景 ----
        if "score" in df.columns:
            _hist(df["score"], "score_distribution", "评分分布", nbins=10)
            metrics["score_unique"] = int(pd.to_numeric(df["score"], errors="coerce").nunique())

        if "shop_id" in df.columns:
            title = "门店销量 Top30" if "sales_qty" in df.columns else "门店评论量 Top30"
            if "sales_qty" in df.columns:
                tmp = df[["shop_id", "sales_qty"]].copy()
                tmp["shop_id"] = tmp["shop_id"].astype(str)
                tmp["sales_qty"] = pd.to_numeric(tmp["sales_qty"], errors="coerce")
                tmp = tmp.dropna(subset=["shop_id", "sales_qty"])
                shop = (
                    tmp.groupby("shop_id", as_index=False)["sales_qty"]
                    .sum()
                    .sort_values("sales_qty", ascending=False)
                    .head(30)
                    .rename(columns={"shop_id": "label"})
                )
                if len(shop):
                    fig = px.bar(shop, x="label", y="sales_qty", title=title)
                    base = ctx.artifact_store.figure_path("shop_review_count").with_suffix("")
                    html, png = save_plotly_figure(fig, base)
                    outputs["shop_review_count"] = str(html)
                    if png:
                        outputs["shop_review_count_png"] = str(png)
                    metrics["shop_count"] = int(df["shop_id"].nunique())
            else:
                _topk_bar(df["shop_id"], "shop_review_count", title)

        if "content" in df.columns:
            lengths = df["content"].fillna("").astype(str).str.len()
            _hist(lengths, "content_length_distribution", "评论长度分布", nbins=40)

        # ---- 销售/订单场景 ----
        if "sales_qty" in df.columns:
            _hist(df["sales_qty"], "sales_qty_distribution", "销量分布", nbins=30)
        if "unit_price" in df.columns:
            _hist(df["unit_price"], "unit_price_distribution", "单价分布", nbins=30)
        if "product_id" in df.columns:
            _topk_bar(df["product_id"], "product_top", "商品销量次数 Top30")
        if "category_id" in df.columns:
            _topk_bar(df["category_id"], "category_top", "类别分布 Top30")

        # ---- 兜底：任意数值列 / 低基数类别列 ----
        if not outputs:
            skip = {"order_id", "review_id"}
            for col in df.columns:
                if col in skip:
                    continue
                num = pd.to_numeric(df[col], errors="coerce")
                if num.notna().sum() >= max(5, int(len(df) * 0.3)):
                    _hist(num, f"dist_{col}", f"{col} 分布", nbins=30)
                    if outputs:
                        break
            if not outputs:
                for col in df.columns:
                    nunique = df[col].nunique(dropna=True)
                    if 2 <= nunique <= 50:
                        _topk_bar(df[col], f"top_{col}", f"{col} Top", value_name="count")
                        if outputs:
                            break

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
                "没有可绘制的字段。支持评论字段 score/shop_id/content，"
                "或销售字段 sales_qty/unit_price/product_id/门店编号/销量/单价 等。"
                f"当前列：{cols[:20]}"
            ),
        )
