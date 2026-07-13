from __future__ import annotations

from pathlib import Path


def save_plotly_figure(fig, base_path: Path) -> tuple[Path, Path | None]:
    """保存 Plotly 图表为 HTML，并尽量导出 PNG 供报告嵌入。"""
    html_path = base_path.with_suffix(".html")
    png_path = base_path.with_suffix(".png")
    fig.write_html(str(html_path))
    try:
        fig.write_image(str(png_path), scale=2)
        return html_path, png_path
    except Exception:
        return html_path, None
