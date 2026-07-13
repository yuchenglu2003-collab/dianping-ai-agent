from __future__ import annotations

from pathlib import Path


def save_plotly_figure(fig, base_path: Path) -> tuple[Path, Path | None]:
    """保存 Plotly 图表为 HTML。云端禁用 kaleido PNG，避免原生崩溃。"""
    html_path = base_path.with_suffix(".html")
    fig.write_html(str(html_path), include_plotlyjs="cdn", full_html=True)
    return html_path, None
