from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px

from src.tools._data_io import load_analysis_frame_from_ctx, resolve_tool_input_path
from src.tools.base import BaseTool, ToolResult
from src.tools.viz._plotly_io import save_plotly_figure


class RfmSegmentTool(BaseTool):
    name = "rfm_segment"
    description = "基于行为/交易构建 RFM 用户分层"

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        input_path = resolve_tool_input_path(ctx, kwargs)
        if not input_path.exists():
            return ToolResult(success=False, error=f"找不到数据: {input_path}")

        max_rows = int(ctx.config.get("defaults", {}).get("behavior_max_rows", 200000))
        df = load_analysis_frame_from_ctx(ctx, input_path, nrows=max_rows)

        if "user_id" not in df.columns:
            return ToolResult(success=False, error="RFM 需要 user_id")

        if "review_time" in df.columns:
            ts = pd.to_datetime(df["review_time"], errors="coerce")
        elif "event_time" in df.columns:
            num = pd.to_numeric(df["event_time"], errors="coerce")
            ts = pd.to_datetime(num, unit="s", errors="coerce")
            if ts.isna().mean() > 0.8:
                ts = pd.to_datetime(df["event_time"], errors="coerce")
        elif "time" in df.columns:
            num = pd.to_numeric(df["time"], errors="coerce")
            ts = pd.to_datetime(num, unit="s", errors="coerce")
        else:
            return ToolResult(success=False, error="RFM 需要时间字段（time/review_time/event_time）")

        work = df.copy()
        work["ts"] = ts
        work = work.dropna(subset=["ts", "user_id"])
        if work.empty:
            return ToolResult(success=False, error="有效时间数据为空")

        if "event_type" in work.columns:
            evt = work["event_type"].astype(str).str.lower()
        elif "behavior" in work.columns:
            evt = work["behavior"].astype(str).str.lower()
        else:
            evt = pd.Series(["pv"] * len(work), index=work.index)

        buy = evt.isin(["buy", "order", "purchase", "购买", "下单"])
        if "sales_qty" in work.columns and "unit_price" in work.columns:
            monetary = (
                pd.to_numeric(work["sales_qty"], errors="coerce").fillna(0)
                * pd.to_numeric(work["unit_price"], errors="coerce").fillna(0)
            )
        else:
            monetary = buy.astype(int)

        ref = work["ts"].max()
        g = (
            work.assign(_m=monetary, user_id=work["user_id"].astype(str))
            .groupby("user_id")
            .agg(
                recency_days=("ts", lambda s: float((ref - s.max()).days)),
                frequency=("ts", "count"),
                monetary=("_m", "sum"),
            )
        )

        def _score(series: pd.Series, higher_better: bool) -> pd.Series:
            try:
                labels = [1, 2, 3, 4, 5] if higher_better else [5, 4, 3, 2, 1]
                return pd.qcut(series.rank(method="first"), 5, labels=labels).astype(int)
            except ValueError:
                return pd.Series([3] * len(series), index=series.index)

        g["R"] = _score(g["recency_days"], higher_better=False)
        g["F"] = _score(g["frequency"], higher_better=True)
        g["M"] = _score(g["monetary"], higher_better=True)

        def segment(row: pd.Series) -> str:
            if row["R"] >= 4 and row["F"] >= 4 and row["M"] >= 4:
                return "重要价值用户"
            if row["R"] >= 4 and row["F"] <= 2:
                return "重要发展用户"
            if row["R"] <= 2 and row["F"] >= 4:
                return "重要保持用户"
            if row["R"] <= 2 and row["F"] <= 2:
                return "一般挽留用户"
            return "一般用户"

        g["segment"] = g.apply(segment, axis=1)
        seg_counts = (
            g["segment"].value_counts().rename_axis("segment").reset_index(name="users")
        )

        fig = px.bar(seg_counts, x="segment", y="users", title="RFM 用户分层人数")
        base = ctx.artifact_store.figure_path("rfm_segments").with_suffix("")
        html, png = save_plotly_figure(fig, base)

        out_csv = Path(ctx.config["paths"].get("features", "data/features")) / f"{ctx.run_id}_rfm_users.csv"
        if not out_csv.is_absolute():
            out_csv = ctx.project_root / out_csv
        out_csv.parent.mkdir(parents=True, exist_ok=True)
        g.reset_index().to_csv(out_csv, index=False)

        strategy = {
            "重要价值用户": "会员权益加码、专属优惠、高客单推荐",
            "重要发展用户": "提升复购：满减券、到店提醒",
            "重要保持用户": "唤醒召回：流失关怀、限时红包",
            "一般挽留用户": "低成本触达：推送爆品、新客礼包",
            "一般用户": "内容种草与基础运营",
        }
        report = ctx.artifact_store.report_path("rfm")
        lines = ["# 用户 RFM 分层与运营策略", ""]
        for _, row in seg_counts.iterrows():
            seg = row["segment"]
            lines.append(f"- {seg}: {int(row['users'])} 人 → {strategy.get(seg, '')}")
        report.write_text("\n".join(lines), encoding="utf-8")

        metrics = {"rfm_users": int(len(g))}
        for k, v in g["segment"].value_counts().items():
            metrics[f"rfm_{k}"] = int(v)

        outputs = {"rfm_segments": str(html), "rfm_report": str(report), "rfm_users": str(out_csv)}
        if png:
            outputs["rfm_segments_png"] = str(png)
        return ToolResult(success=True, outputs=outputs, metrics=metrics, message="RFM 分层完成")
