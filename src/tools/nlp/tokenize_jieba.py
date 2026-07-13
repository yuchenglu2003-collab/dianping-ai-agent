from __future__ import annotations

from pathlib import Path
from typing import Any

import jieba
import pandas as pd

from src.tools._data_io import load_analysis_frame_from_ctx, resolve_tool_input_path
from src.tools.base import BaseTool, ToolResult


DEFAULT_STOPWORDS = {
    "的", "了", "和", "是", "我", "也", "很", "都", "在", "有", "就", "不", "人", "都",
    "一个", "没有", "什么", "这个", "那个", "还是", "比较", "感觉", "真的", "可以",
    "我们", "你们", "他们", "啊", "呢", "吧", "吗", "哦", "哈", "嗯", "呀",
}


class TokenizeJiebaTool(BaseTool):
    name = "tokenize_jieba"
    description = "中文分词并统计词频"
    required_columns = ["content"]

    def run(self, ctx, **kwargs: Any) -> ToolResult:
        input_path = resolve_tool_input_path(ctx, kwargs)
        if not input_path.exists():
            return ToolResult(success=False, error=f"找不到清洗数据: {input_path}")

        df = load_analysis_frame_from_ctx(ctx, input_path)
        if "content" not in df.columns:
            return ToolResult(
                success=False,
                error=f"缺少 content 字段（或 cus_comment 等别名）。当前列：{list(df.columns)[:20]}",
            )

        stopwords = set(DEFAULT_STOPWORDS)
        freq: dict[str, int] = {}
        tokens_list: list[str] = []
        for text in df["content"].astype(str).tolist():
            words = [w.strip() for w in jieba.lcut(text) if len(w.strip()) >= 2 and w.strip() not in stopwords]
            tokens_list.append(" ".join(words))
            for w in words:
                freq[w] = freq.get(w, 0) + 1

        out_dir = Path(ctx.paths.get("features", ctx.project_root / "data" / "features"))
        out_dir.mkdir(parents=True, exist_ok=True)
        token_path = out_dir / f"{ctx.task.task_id}_tokens.csv"
        pd.DataFrame({"tokens": tokens_list}).to_csv(token_path, index=False)

        top = sorted(freq.items(), key=lambda x: x[1], reverse=True)[:50]
        top_path = out_dir / f"{ctx.task.task_id}_topk_words.csv"
        pd.DataFrame(top, columns=["word", "count"]).to_csv(top_path, index=False)

        return ToolResult(
            success=True,
            outputs={"tokens": str(token_path), "topk_words": str(top_path)},
            metrics={"unique_tokens": len(freq), "top1_word": top[0][0] if top else "", "top1_count": top[0][1] if top else 0},
            message=f"分词完成，词表大小 {len(freq)}",
        )
