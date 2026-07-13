from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pandas as pd

from src.tools.base import BaseTool, ToolResult


FIGURE_LABELS = {
    "score_distribution": "评分分布",
    "shop_review_count": "门店评论量 Top30",
    "content_length_distribution": "评论长度分布",
    "reviews_over_time": "每日评论量趋势",
    "score_over_time": "每日均分趋势",
    "wordcloud": "评论关键词词云",
}

METRIC_LABELS = {
    "clean_row_count": "清洗后记录数",
    "raw_rows": "原始记录数",
    "dropped_rows": "剔除记录数",
    "score_mean": "平均评分",
    "score_std": "评分标准差",
    "shop_count": "门店数量",
    "content_len_mean": "评论平均长度",
    "content_len_median": "评论长度中位数",
    "timeseries_days": "时序覆盖天数",
    "timeseries_start": "时序起始日期",
    "timeseries_end": "时序结束日期",
    "top1_word": "最高频词",
    "top1_count": "最高频词出现次数",
    "unique_tokens": "独立词数",
}


def _needs_clean_data(task_goal: str, deliverables: list[str]) -> bool:
    text = f"{task_goal} {' '.join(deliverables)}".lower()
    keys = ["清洗", "干净", "clean", "缺失", "异常", "去重"]
    return any(k in text for k in keys)


def _bundle_report_dir(ctx) -> Path:
    return Path(ctx.paths.get("artifacts", "artifacts")) / "reports" / f"{ctx.task.task_id}_{ctx.run_id}"


def _copy_figures(ctx, bundle_dir: Path) -> list[tuple[str, str]]:
    assets = bundle_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    embedded: list[tuple[str, str]] = []

    seen: set[str] = set()
    for key, path_str in ctx.state.artifacts.items():
        if key.endswith("_png"):
            continue
        if key in seen:
            continue
        path = Path(path_str)
        if not path.exists():
            continue

        png_path_str = ctx.state.artifacts.get(f"{key}_png")
        if png_path_str:
            png_path = Path(png_path_str)
        elif path.suffix.lower() == ".png":
            png_path = path
        else:
            png_path = None

        if png_path and png_path.exists():
            dest = assets / f"{key}.png"
            shutil.copy2(png_path, dest)
            embedded.append((FIGURE_LABELS.get(key, key), f"assets/{key}.png"))
            seen.add(key)
        elif path.suffix.lower() == ".html":
            dest = assets / f"{key}.html"
            shutil.copy2(path, dest)
            label = FIGURE_LABELS.get(key, key)
            embedded.append((label, f"assets/{key}.html", "link"))
            seen.add(key)
    return embedded


def _append_clean_data_section(ctx, bundle_dir: Path, lines: list[str]) -> None:
    clean_csv = ctx.state.artifacts.get("clean_csv") or ctx.state.artifacts.get("clean_data")
    if not clean_csv:
        return
    src = Path(clean_csv)
    if not src.exists():
        return

    if src.suffix == ".parquet":
        df = pd.read_parquet(src)
        dest = bundle_dir / "clean_data.csv"
        df.to_csv(dest, index=False)
    else:
        dest = bundle_dir / "clean_data.csv"
        shutil.copy2(src, dest)
        df = pd.read_csv(dest)

    lines += ["", "## 清洗后数据", ""]
    lines.append(f"- 文件：`clean_data.csv`（共 {len(df)} 行）")
    lines.append("")
    preview = df.head(10)
    try:
        lines.append(preview.to_markdown(index=False))
    except Exception:
        lines.append("```")
        lines.append(preview.to_string(index=False))
        lines.append("```")


def _append_keywords_section(ctx, lines: list[str]) -> None:
    path = ctx.state.artifacts.get("keyword_conclusion")
    if path and Path(path).exists():
        text = Path(path).read_text(encoding="utf-8")
        # 去掉重复一级标题
        text = re.sub(r"^#\s+.*\n", "", text, count=1).strip()
        if text:
            lines += ["", "## 关键词洞察", "", text]
        return

    topk = ctx.state.artifacts.get("topk_words")
    if topk and Path(topk).exists():
        df = pd.read_csv(topk).head(15)
        lines += ["", "## 关键词洞察", ""]
        for _, row in df.iterrows():
            lines.append(f"- {row['word']}: {row['count']}")


class RenderReportTool(BaseTool):
    name = "render_report"
    description = "生成整合图表与数据的 Markdown 报告"

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        metrics = dict(ctx.metric_store.to_dict())
        metrics.update(ctx.state.metrics)

        bundle_dir = _bundle_report_dir(ctx)
        bundle_dir.mkdir(parents=True, exist_ok=True)

        title = (ctx.task.report or {}).get("title") or "数据分析报告"
        lines = [f"# {title}", "", "## 任务要求", "", ctx.task.goal or "（未填写）", ""]

        # 数据概况
        if ctx.schema and ctx.schema.primary():
            p = ctx.schema.primary()
            lines += [
                "## 数据概况",
                "",
                f"- 数据文件：`{Path(p.path).name}`",
                f"- 原始行数：{p.rows}",
                f"- 字段数：{len(p.columns)}",
                f"- 推断类型：{p.table_kind}",
                "",
            ]

        # 关键指标（仅展示业务相关）
        skip_keys = {"missing_packages", "table_count", "primary_rows", "primary_cols", "primary_table_kind", "wordcloud_mode", "topk_used", "report_chars", "figure_count", "dropped_na_rows"}
        show_metrics = {k: v for k, v in metrics.items() if k not in skip_keys and not k.startswith("non_null_rate_")}
        if show_metrics:
            lines += ["## 关键指标", ""]
            for k, v in show_metrics.items():
                label = METRIC_LABELS.get(k, k)
                if isinstance(v, float):
                    lines.append(f"- **{label}**：{v:.4f}" if abs(v) < 1000 else f"- **{label}**：{v:.2f}")
                else:
                    lines.append(f"- **{label}**：{v}")
            lines.append("")

        # 图表嵌入
        figures = _copy_figures(ctx, bundle_dir)
        if figures:
            lines += ["## 图表", ""]
            for item in figures:
                label, rel = item[0], item[1]
                kind = item[2] if len(item) > 2 else "image"
                lines.append(f"### {label}")
                lines.append("")
                if kind == "link":
                    lines.append(f"[点击查看交互图表]({rel})")
                else:
                    lines.append(f"![{label}]({rel})")
                lines.append("")

        # 关键词
        _append_keywords_section(ctx, lines)

        # 清洗数据（按需或任务涉及清洗时附带）
        need_clean = _needs_clean_data(ctx.task.goal, ctx.task.deliverables) or "clean_data" in ctx.state.artifacts
        if need_clean and ("clean_csv" in ctx.state.artifacts or "clean_data" in ctx.state.artifacts):
            _append_clean_data_section(ctx, bundle_dir, lines)

        # 结论
        conclusions: list[str] = []
        if metrics.get("clean_row_count") is not None:
            conclusions.append(f"清洗后保留 {metrics['clean_row_count']} 条有效记录。")
        if metrics.get("score_mean") is not None:
            conclusions.append(f"整体平均评分为 {float(metrics['score_mean']):.2f}。")
        if metrics.get("shop_count"):
            conclusions.append(f"共覆盖 {metrics['shop_count']} 家门店。")
        if metrics.get("top1_word"):
            conclusions.append(f"评论最高频词为「{metrics['top1_word']}」，出现 {metrics.get('top1_count', 0)} 次。")
        if metrics.get("timeseries_days"):
            conclusions.append(
                f"时序分析覆盖 {metrics.get('timeseries_start')} 至 {metrics.get('timeseries_end')}。"
            )
        if not conclusions:
            conclusions.append("分析已完成，详细结果见上文指标与图表。")

        lines += ["## 分析结论", ""]
        lines.extend(f"- {c}" for c in conclusions)
        lines += ["", "---", f"*run_id: {ctx.run_id}*"]

        content = "\n".join(lines)
        out = bundle_dir / "report.md"
        out.write_text(content, encoding="utf-8")

        # 兼容旧路径：reports 根目录也放一份
        legacy = ctx.artifact_store.report_path("report")
        legacy.write_text(content, encoding="utf-8")

        ctx.metric_store.save(ctx.artifact_store.metrics_path())

        outputs = {"report": str(out), "report_bundle": str(bundle_dir)}
        if (bundle_dir / "clean_data.csv").exists():
            outputs["clean_data_download"] = str(bundle_dir / "clean_data.csv")

        return ToolResult(
            success=True,
            outputs=outputs,
            metrics={"report_chars": len(content), "figure_count": len(figures)},
            message=f"报告已生成: {out}",
        )
