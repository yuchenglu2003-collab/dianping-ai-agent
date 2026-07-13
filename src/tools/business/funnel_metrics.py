from __future__ import annotations

from typing import Any

import pandas as pd
import plotly.express as px

from src.data_resolver import load_table
from src.infra.schema_adapter import apply_schema_hints, rename_to_standard
from src.tools._data_io import resolve_tool_input_path
from src.tools.base import BaseTool, ToolResult
from src.tools.viz._plotly_io import save_plotly_figure


class FunnelMetricsTool(BaseTool):
    name = "funnel_metrics"
    description = "行为漏斗与 PV/UV/CTR/CVR 等指标（behavior 日志）"

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        input_path = resolve_tool_input_path(ctx, kwargs)
        if not input_path.exists():
            return ToolResult(success=False, error=f"找不到数据: {input_path}")

        max_rows = int(ctx.config.get("defaults", {}).get("behavior_max_rows", 200000))
        raw = load_table(input_path, nrows=max_rows)
        mapped = apply_schema_hints(raw, ctx.config.get("schema_hints") or {})
        df = rename_to_standard(raw, mapped)

        if "event_type" not in df.columns and "behavior" in df.columns:
            df = df.rename(columns={"behavior": "event_type"})

        if "event_type" not in df.columns or "user_id" not in df.columns:
            return ToolResult(
                success=False,
                error=f"漏斗分析需要 event_type/behavior 与 user_id。当前列：{list(df.columns)[:20]}",
            )

        evt = df["event_type"].astype(str).str.lower().str.strip()
        stages = [
            ("曝光/浏览 PV", evt.isin(["pv", "view", "click", "曝光", "浏览"])),
            ("意向(收藏/加购)", evt.isin(["fav", "cart", "collect", "收藏", "加购"])),
            ("转化购买", evt.isin(["buy", "order", "purchase", "购买", "下单"])),
        ]
        if not any(m.any() for _, m in stages):
            top = evt.value_counts().head(4).index.tolist()
            stages = [(f"阶段-{b}", evt.eq(b)) for b in top]

        funnel_rows = []
        prev_users = None
        for name, mask in stages:
            users = set(df.loc[mask, "user_id"].astype(str))
            cnt = len(users)
            events = int(mask.sum())
            cvr = (cnt / prev_users) if prev_users else 1.0
            funnel_rows.append({"stage": name, "uv": cnt, "pv": events, "cvr_from_prev": cvr})
            prev_users = cnt or prev_users

        fdf = pd.DataFrame(funnel_rows)
        fig = px.funnel(fdf, x="uv", y="stage", title="用户行为流量漏斗（UV）")
        base = ctx.artifact_store.figure_path("behavior_funnel").with_suffix("")
        html, png = save_plotly_figure(fig, base)

        total_pv = int(len(df))
        total_uv = int(df["user_id"].nunique())
        buy_mask = evt.isin(["buy", "order", "purchase", "购买", "下单"])
        buy_uv = int(df.loc[buy_mask, "user_id"].nunique()) if buy_mask.any() else 0
        metrics: dict[str, Any] = {
            "pv": total_pv,
            "uv": total_uv,
            "dau_proxy": total_uv,
            "buy_uv": buy_uv,
            "cvr": float(buy_uv / total_uv) if total_uv else 0.0,
            "ctr_proxy": float(fdf.iloc[1]["uv"] / fdf.iloc[0]["uv"]) if len(fdf) > 1 and fdf.iloc[0]["uv"] else 0.0,
        }

        if "sales_qty" in df.columns and "unit_price" in df.columns:
            gmv = float(
                (
                    pd.to_numeric(df["sales_qty"], errors="coerce").fillna(0)
                    * pd.to_numeric(df["unit_price"], errors="coerce").fillna(0)
                ).sum()
            )
        else:
            gmv = float(buy_mask.sum())
        metrics["gmv_proxy"] = gmv
        metrics["arpu"] = float(gmv / total_uv) if total_uv else 0.0
        metrics["arppu"] = float(gmv / buy_uv) if buy_uv else 0.0

        report = ctx.artifact_store.report_path("funnel")
        lines = [
            "# 用户行为流量漏斗分析",
            "",
            f"- PV: {metrics['pv']}",
            f"- UV: {metrics['uv']}",
            f"- Buy UV: {metrics['buy_uv']}",
            f"- CVR: {metrics['cvr']:.2%}",
            f"- CTR(proxy): {metrics['ctr_proxy']:.2%}",
            f"- GMV(proxy): {metrics['gmv_proxy']:.2f}",
            f"- ARPU: {metrics['arpu']:.4f}",
            f"- ARPPU: {metrics['arppu']:.4f}",
            "",
            "## 漏斗",
            "",
            fdf.to_string(index=False),
        ]
        report.write_text("\n".join(lines), encoding="utf-8")

        outputs = {"behavior_funnel": str(html), "funnel_report": str(report)}
        if png:
            outputs["behavior_funnel_png"] = str(png)
        return ToolResult(success=True, outputs=outputs, metrics=metrics, message="漏斗指标计算完成")
