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

            # LLM 优先，规则补洞
            mapping = merge_column_mappings(llm_map, rule_map)
            kind = str(data.get("table_kind") or table.table_kind or "unknown")
            notes = [str(n) for n in (data.get("notes") or [])]
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
