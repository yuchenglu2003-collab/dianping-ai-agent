from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px

from src.tools._data_io import load_analysis_frame_from_ctx, resolve_tool_input_path
from src.tools.base import BaseTool, ToolResult
from src.tools.viz._plotly_io import save_plotly_figure


ASPECT_COLS = ("taste", "environment", "service")
ASPECT_LABELS = {"taste": "口味", "environment": "环境", "service": "服务"}


def _aspect_positive(series: pd.Series) -> pd.Series:
    """方面字段可能是 很好/好/一般 或数值。"""
    s = series.astype(str).str.strip()
    pos_words = {"非常好", "很好", "好", "优秀", "满意", "5", "4", "4.0", "5.0"}
    return s.isin(pos_words) | pd.to_numeric(series, errors="coerce").fillna(0).ge(4)


class AttributionAspectsTool(BaseTool):
    name = "attribution_aspects"
    description = "好评归因：口味/服务/环境占比，以及评论长度与好评关系"

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        input_path = resolve_tool_input_path(ctx, kwargs)
        if not input_path.exists():
            return ToolResult(success=False, error=f"找不到数据: {input_path}")

        df = load_analysis_frame_from_ctx(ctx, input_path)
        threshold = float(ctx.params.get("positive_threshold", 4))
        outputs: dict[str, str] = {}
        metrics: dict[str, Any] = {}

        if "score" not in df.columns:
            return ToolResult(success=False, error="缺少 score/stars 字段，无法做好评归因")

        score = pd.to_numeric(df["score"], errors="coerce")
        positive = score >= threshold
        metrics["positive_rate"] = float(positive.mean())
        metrics["positive_threshold"] = threshold

        # 方面占比（在好评中）
        aspect_rows = []
        for col in ASPECT_COLS:
            if col not in df.columns:
                continue
            mask = _aspect_positive(df[col])
            # 好评子集中该方面为正向的比例
            if positive.any():
                rate = float(mask[positive].mean())
            else:
                rate = 0.0
            aspect_rows.append({"aspect": ASPECT_LABELS.get(col, col), "positive_share": rate})
            metrics[f"aspect_positive_share_{col}"] = rate

        if aspect_rows:
            adf = pd.DataFrame(aspect_rows)
            fig = px.bar(adf, x="aspect", y="positive_share", title="好评中各维度正向占比")
            base = ctx.artifact_store.figure_path("aspect_attribution").with_suffix("")
            html, png = save_plotly_figure(fig, base)
            outputs["aspect_attribution"] = str(html)
            if png:
                outputs["aspect_attribution_png"] = str(png)

        # 评论长度 vs 好评
        if "content" in df.columns or "content_len" in df.columns:
            if "content_len" in df.columns:
                lengths = pd.to_numeric(df["content_len"], errors="coerce")
            else:
                lengths = df["content"].fillna("").astype(str).str.len()
            tmp = pd.DataFrame({"length": lengths, "positive": positive.astype(int)}).dropna()
            if len(tmp):
                tmp["len_bin"] = pd.qcut(tmp["length"].clip(lower=1), q=min(5, tmp["length"].nunique()), duplicates="drop")
                by = tmp.groupby("len_bin", observed=False)["positive"].mean().reset_index()
                by["len_bin"] = by["len_bin"].astype(str)
                fig = px.bar(by, x="len_bin", y="positive", title="评论长度分箱 vs 好评率")
                base = ctx.artifact_store.figure_path("length_attribution").with_suffix("")
                html, png = save_plotly_figure(fig, base)
                outputs["length_attribution"] = str(html)
                if png:
                    outputs["length_attribution_png"] = str(png)
                metrics["pos_len_mean"] = float(tmp.loc[tmp["positive"] == 1, "length"].mean()) if tmp["positive"].any() else 0.0
                metrics["neg_len_mean"] = float(tmp.loc[tmp["positive"] == 0, "length"].mean()) if (tmp["positive"] == 0).any() else 0.0

        # 简要 markdown 结论
        lines = ["# 影响用户好评的关键因素归因", "", f"- 好评阈值: score >= {threshold}", f"- 好评率: {metrics.get('positive_rate', 0):.2%}"]
        for row in aspect_rows:
            lines.append(f"- {row['aspect']} 在好评中正向占比: {row['positive_share']:.2%}")
        if "pos_len_mean" in metrics:
            lines += [
                f"- 好评平均评论长度: {metrics['pos_len_mean']:.1f}",
                f"- 非好评平均评论长度: {metrics['neg_len_mean']:.1f}",
            ]
        report = ctx.artifact_store.report_path("attribution")
        report.write_text("\n".join(lines), encoding="utf-8")
        outputs["attribution_report"] = str(report)

        ok = bool(outputs)
        return ToolResult(
            success=ok,
            outputs=outputs,
            metrics=metrics,
            message="归因分析完成" if ok else "归因分析无可用字段",
            error=None if ok else "缺少方面字段或内容字段",
        )
