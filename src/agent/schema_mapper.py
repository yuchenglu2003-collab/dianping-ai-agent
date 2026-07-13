from __future__ import annotations

import json
from typing import Any

from src.data_resolver import SchemaSummary, TableSummary
from src.infra.llm_gateway import LLMGateway
from src.infra.llm_prompts import load_prompt
from src.infra.schema_adapter import apply_schema_hints


STANDARD_FIELDS = {
    "user_id",
    "shop_id",
    "review_id",
    "order_id",
    "product_id",
    "category_id",
    "score",
    "content",
    "content_len",
    "review_time",
    "event_time",
    "event_type",
    "unit_price",
    "sales_qty",
    "taste",
    "environment",
    "service",
}


def merge_column_mappings(*maps: dict[str, str]) -> dict[str, str]:
    """合并 raw->std 映射；后写不覆盖已占用的 std，也不覆盖已有 raw。"""
    out: dict[str, str] = {}
    used_std: set[str] = set()
    for m in maps:
        for raw, std in (m or {}).items():
            raw_s, std_s = str(raw), str(std)
            if not raw_s or std_s not in STANDARD_FIELDS:
                continue
            if raw_s in out or std_s in used_std:
                continue
            out[raw_s] = std_s
            used_std.add(std_s)
    return out


def rule_mapping_from_table(table: TableSummary, schema_hints: dict[str, list[str]] | None) -> dict[str, str]:
    """用静态 hints 得到 raw->std（基于列名，不读全表）。"""
    # 构造假 df 列集合：用 TableSummary.columns
    class _Cols:
        def __init__(self, cols: list[str]):
            self.columns = cols

    mapped = apply_schema_hints(_Cols(table.columns), schema_hints or {})
    return {str(k): str(v) for k, v in mapped.items()}


def _sample_values(table: TableSummary, col: str) -> list[Any]:
    vals: list[Any] = []
    for row in table.sample_rows or []:
        if isinstance(row, dict) and col in row:
            vals.append(row.get(col))
    return vals


def looks_like_score_column(table: TableSummary, col: str) -> bool:
    """样例需像评分：数值 1–5 / 10–50；拒绝 sml-str40 这类展示编码（应优先 stars）。"""
    import re

    vals = _sample_values(table, col)
    if not vals:
        # 无样例时：列名像评分才接受；排除 comment_star 展示编码列名
        low = col.lower()
        if "comment_star" in low or low.endswith("_str"):
            return False
        return any(k in low for k in ("star", "score", "rating", "评分", "星级"))

    # 展示编码（sml-str40）不当作可靠 score，留给规则映射 stars
    non_null = [v for v in vals if v is not None]
    if non_null and sum(str(v).lower().startswith("sml-") for v in non_null) >= max(1, len(non_null) // 2):
        return False

    ok = 0
    for v in non_null:
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            if 1 <= float(v) <= 5 or 10 <= float(v) <= 50:
                ok += 1
            continue
        s = str(v).strip()
        m = re.fullmatch(r"\d+(?:\.\d+)?", s)
        if not m:
            continue
        num = float(m.group(0))
        if 1 <= num <= 5 or 10 <= num <= 50:
            ok += 1
    return ok >= max(1, len(non_null) // 2)


def looks_like_text_column(table: TableSummary, col: str) -> bool:
    vals = _sample_values(table, col)
    if not vals:
        low = col.lower()
        return any(k in low for k in ("comment", "content", "review", "text", "评论", "评价"))
    textish = 0
    for v in vals:
        if v is None:
            continue
        s = str(v).strip()
        if len(s) >= 4 and not s.replace(".", "", 1).isdigit():
            textish += 1
    return textish >= max(1, len([v for v in vals if v is not None]) // 2)


def sanitize_llm_mapping(table: TableSummary, llm_map: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """丢掉明显不合理的 score/content 映射。"""
    out = dict(llm_map)
    notes: list[str] = []
    for raw, std in list(out.items()):
        if std == "score" and not looks_like_score_column(table, raw):
            notes.append(f"拒绝不可靠 score 映射: {raw}")
            del out[raw]
        elif std == "content" and not looks_like_text_column(table, raw):
            notes.append(f"拒绝不可靠 content 映射: {raw}")
            del out[raw]
    return out, notes


class LLMSchemaMapper:
    """用大模型识别原始列 -> 标准字段；失败则退回规则映射。"""

    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    def map(
        self,
        schema: SchemaSummary,
        *,
        schema_hints: dict[str, list[str]] | None = None,
        goal_text: str = "",
    ) -> dict[str, Any]:
        table = schema.primary()
        if table is None:
            return {"table_kind": "unknown", "mapping": {}, "source": "empty", "notes": ["无数据表"]}

        rule_map = rule_mapping_from_table(table, schema_hints)
        payload = {
            "columns": table.columns,
            "dtypes": table.dtypes,
            "sample_rows": (table.sample_rows or [])[:3],
            "rule_mapping_suggestion": rule_map,
            "user_goal": (goal_text or "")[:500],
        }
        try:
            data = self.gateway.chat_json(
                [
                    {"role": "system", "content": load_prompt("system_schema_mapper.md")},
                    {
                        "role": "user",
                        "content": (
                            "请识别字段映射，输出 JSON。\n"
                            + json.dumps(payload, ensure_ascii=False)
                        ),
                    },
                ],
                stage="schema_mapper",
            )
            llm_map_raw = data.get("mapping") or {}
            llm_map: dict[str, str] = {}
            if isinstance(llm_map_raw, dict):
                for k, v in llm_map_raw.items():
                    if str(k) in table.columns and str(v) in STANDARD_FIELDS:
                        llm_map[str(k)] = str(v)

            llm_map, reject_notes = sanitize_llm_mapping(table, llm_map)
            # LLM 优先，规则补洞（被拒绝的 score/content 可由 rules 补上 stars 等）
            mapping = merge_column_mappings(llm_map, rule_map)
            kind = str(data.get("table_kind") or table.table_kind or "unknown")
            notes = [str(n) for n in (data.get("notes") or [])] + reject_notes
            return {
                "table_kind": kind,
                "mapping": mapping,
                "source": "llm+rules",
                "notes": notes,
            }
        except Exception as e:
            return {
                "table_kind": table.table_kind or "unknown",
                "mapping": rule_map,
                "source": "rules_fallback",
                "notes": [f"LLM 字段识别失败，已用规则映射: {e}"],
            }
