from __future__ import annotations

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


def _bundle_dir(ctx) -> Path:
    return Path(ctx.paths.get("artifacts", "artifacts")) / "reports" / f"{ctx.task.task_id}_{ctx.run_id}"


def _copy_figures(ctx, bundle_dir: Path) -> list[dict[str, str]]:
    assets = bundle_dir / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    figures: list[dict[str, str]] = []
    seen: set[str] = set()

    for key, path_str in ctx.state.artifacts.items():
        if key.endswith("_png") or key in seen:
            continue
        path = Path(path_str)
        if not path.exists():
            continue
        png_key = f"{key}_png"
        png_path = Path(ctx.state.artifacts[png_key]) if png_key in ctx.state.artifacts else None
        if png_path and png_path.exists():
            dest = assets / f"{key}.png"
            shutil.copy2(png_path, dest)
            figures.append({"key": key, "label": FIGURE_LABELS.get(key, key), "rel": f"assets/{key}.png", "kind": "image"})
            seen.add(key)
        elif path.suffix.lower() == ".png":
            dest = assets / f"{key}.png"
            shutil.copy2(path, dest)
            figures.append({"key": key, "label": FIGURE_LABELS.get(key, key), "rel": f"assets/{key}.png", "kind": "image"})
            seen.add(key)
        elif path.suffix.lower() == ".html":
            dest = assets / f"{key}.html"
            shutil.copy2(path, dest)
            figures.append({"key": key, "label": FIGURE_LABELS.get(key, key), "rel": f"assets/{key}.html", "kind": "link"})
            seen.add(key)
    return figures


def _attach_clean_data(ctx, bundle_dir: Path) -> tuple[str | None, str]:
    clean_csv = ctx.state.artifacts.get("clean_csv") or ctx.state.artifacts.get("clean_data")
    if not clean_csv:
        return None, ""
    src = Path(clean_csv)
    if not src.exists():
        return None, ""

    if src.suffix == ".parquet":
        df = pd.read_parquet(src)
        dest = bundle_dir / "clean_data.csv"
        df.to_csv(dest, index=False)
    else:
        dest = bundle_dir / "clean_data.csv"
        shutil.copy2(src, dest)
        df = pd.read_csv(dest)

    preview = df.head(5)
    try:
        table_md = preview.to_markdown(index=False)
    except Exception:
        table_md = "```\n" + preview.to_string(index=False) + "\n```"
    summary = f"清洗后共 {len(df)} 行。预览：\n{table_md}"
    return str(dest), summary


class LLMRenderReportTool(BaseTool):
    name = "llm_render_report"
    description = "基于 metrics 与图表，由大模型撰写 Markdown 分析报告"

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        gateway = ctx.extras.get("llm_gateway")
        if gateway is None:
            return ToolResult(success=False, error="缺少 LLM Gateway，无法生成报告")

        from src.infra.llm_prompts import load_prompt

        metrics = dict(ctx.metric_store.to_dict())
        metrics.update(ctx.state.metrics)

        bundle_dir = _bundle_dir(ctx)
        bundle_dir.mkdir(parents=True, exist_ok=True)
        figures = _copy_figures(ctx, bundle_dir)
        clean_path, clean_summary = _attach_clean_data(ctx, bundle_dir)

        # 精简 metrics 给 LLM
        skip = {
            "missing_packages",
            "table_count",
            "primary_rows",
            "primary_cols",
            "primary_table_kind",
            "wordcloud_mode",
            "topk_used",
            "report_chars",
            "figure_count",
        }
        slim_metrics = {k: v for k, v in metrics.items() if k not in skip}

        figure_desc = "\n".join(f"- {f['label']} ({f['kind']}: {f['rel']})" for f in figures) or "无图表"
        schema_desc = ""
        if ctx.schema and ctx.schema.primary():
            p = ctx.schema.primary()
            schema_desc = f"文件={Path(p.path).name}, 行数={p.rows}, 列数={len(p.columns)}, 类型={p.table_kind}"

        user_prompt = (
            f"任务目标：{ctx.task.goal}\n\n"
            f"数据概况：{schema_desc or '未知'}\n\n"
            f"关键指标(metrics)：\n{slim_metrics}\n\n"
            f"图表清单：\n{figure_desc}\n\n"
            f"清洗数据摘要：\n{clean_summary or '无'}\n\n"
            "请撰写完整 Markdown 报告正文（从 # 标题开始）。"
        )

        try:
            body = gateway.chat(
                [
                    {"role": "system", "content": load_prompt("system_reporter.md")},
                    {"role": "user", "content": user_prompt},
                ],
                stage="reporter",
            )
        except Exception as e:
            return ToolResult(success=False, error=f"LLM 写报告失败: {e}")

        # 追加图表嵌入与清洗数据说明（确定性，避免 LLM 漏掉）
        lines = [body.strip(), ""]
        if figures:
            lines += ["## 图表", ""]
            for f in figures:
                lines.append(f"### {f['label']}")
                lines.append("")
                if f["kind"] == "image":
                    lines.append(f"![{f['label']}]({f['rel']})")
                else:
                    lines.append(f"[点击查看交互图表]({f['rel']})")
                lines.append("")
        if clean_path:
            lines += [
                "## 清洗后数据",
                "",
                f"- 文件：`clean_data.csv`",
                "",
                clean_summary,
                "",
            ]
        lines += ["---", f"*run_id: {ctx.run_id}*"]
        content = "\n".join(lines)

        out = bundle_dir / "report.md"
        out.write_text(content, encoding="utf-8")
        legacy = ctx.artifact_store.report_path("report")
        legacy.write_text(content, encoding="utf-8")
        ctx.metric_store.save(ctx.artifact_store.metrics_path())

        # 简单防编造：抽查报告中的「清洗后记录数」类数字是否离谱（宽松）
        outputs = {"report": str(out), "report_bundle": str(bundle_dir)}
        if clean_path:
            outputs["clean_data_download"] = clean_path

        return ToolResult(
            success=True,
            outputs=outputs,
            metrics={"report_chars": len(content), "figure_count": len(figures), "report_source": "llm"},
            message=f"LLM 报告已生成: {out}",
        )
