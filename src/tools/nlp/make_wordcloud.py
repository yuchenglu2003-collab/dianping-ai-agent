from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from src.tools.base import BaseTool, ToolResult


class MakeWordcloudTool(BaseTool):
    name = "make_wordcloud"
    description = "根据词频生成词云图"

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        topk_path = Path(kwargs.get("input") or ctx.state.artifacts.get("topk_words") or "")
        if not topk_path.exists():
            return ToolResult(success=False, error=f"找不到词频文件: {topk_path}")

        df = pd.read_csv(topk_path)
        if df.empty or "word" not in df.columns:
            return ToolResult(success=False, error="词频文件为空")

        freqs = dict(zip(df["word"].astype(str), df["count"].astype(int)))

        try:
            import os

            os.environ.setdefault("MPLCONFIGDIR", str(ctx.project_root / ".mplconfig"))
            (ctx.project_root / ".mplconfig").mkdir(parents=True, exist_ok=True)

            import matplotlib

            matplotlib.use("Agg")
            from wordcloud import WordCloud
            import matplotlib.pyplot as plt

            font = _find_cjk_font()
            wc_kwargs = {
                "width": 1200,
                "height": 800,
                "background_color": "white",
                "max_words": 100,
            }
            if font:
                wc_kwargs["font_path"] = font
            wc = WordCloud(**wc_kwargs).generate_from_frequencies(freqs)

            out = ctx.artifact_store.figure_path("wordcloud", ext="png")
            # 直接保存，避免 GUI/imshow 在无显示环境下崩溃
            wc.to_file(str(out))
            plt.close("all")
        except Exception as e:
            # 降级：输出 html 词频条形图
            import plotly.express as px

            fig = px.bar(df.head(30), x="word", y="count", title="高频词 Top30（词云降级）")
            out = ctx.artifact_store.figure_path("wordcloud_fallback")
            fig.write_html(str(out))
            return ToolResult(
                success=True,
                outputs={"wordcloud": str(out)},
                metrics={"wordcloud_mode": "fallback_bar"},
                message=f"词云不可用，已降级为条形图: {e}",
            )

        # 结论 markdown
        lines = ["# 用户评论关键词初步结论", "", "## Top 关键词", ""]
        for _, row in df.head(15).iterrows():
            lines.append(f"- {row['word']}: {row['count']}")
        lines += ["", "## 简要解读", "", "高频词反映用户在口味、服务、环境等方面的关注点，可作为后续归因与运营优化的线索。"]
        conclusion = ctx.artifact_store.report_path("keyword_conclusion")
        conclusion.write_text("\n".join(lines), encoding="utf-8")

        return ToolResult(
            success=True,
            outputs={"wordcloud": str(out), "keyword_conclusion": str(conclusion)},
            metrics={"wordcloud_mode": "png", "topk_used": int(len(df))},
            message="词云与关键词结论已生成",
        )


def _find_cjk_font() -> str | None:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/System/Library/Fonts/Hiragino Sans GB.ttc",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    return None
