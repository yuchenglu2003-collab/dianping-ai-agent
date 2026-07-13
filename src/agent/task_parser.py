from __future__ import annotations

import json
from typing import Any

from src.data_resolver import SchemaSummary
from src.infra.llm_gateway import LLMGateway
from src.infra.llm_prompts import load_prompt
from src.task_loader import _slugify
from src.task_spec import TaskSpec


class LLMTaskParser:
    """用大模型把自然语言任务解析成 TaskSpec。"""

    def __init__(self, gateway: LLMGateway):
        self.gateway = gateway

    def parse(self, goal_text: str, schema: SchemaSummary | None = None) -> TaskSpec:
        goal_text = (goal_text or "").strip()
        if not goal_text:
            raise ValueError("任务要求不能为空")

        schema_payload = schema.to_dict() if schema else {"tables": []}
        # 压缩样例，控制 token
        for t in schema_payload.get("tables", []):
            t["sample_rows"] = (t.get("sample_rows") or [])[:2]

        user_prompt = (
            f"用户任务：\n{goal_text}\n\n"
            f"数据 schema 摘要：\n{json.dumps(schema_payload, ensure_ascii=False)}\n\n"
            "请输出 JSON，字段包括：goal, deliverables, acceptance, params, assumptions, clarifications, report_title"
        )
        data = self.gateway.chat_json(
            [
                {"role": "system", "content": load_prompt("system_task_parser.md")},
                {"role": "user", "content": user_prompt},
            ],
            stage="task_parser",
        )
        return task_spec_from_llm_dict(data, fallback_goal=goal_text)


def _as_dict(value: Any) -> dict[str, Any]:
    """LLM 常把 object 写成 list/string；安全转成 dict，避免 dict([...]) 崩掉。"""
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(k): v for k, v in value.items()}
    if isinstance(value, list):
        out: dict[str, Any] = {}
        for item in value:
            if isinstance(item, dict):
                out.update({str(k): v for k, v in item.items()})
            elif isinstance(item, (list, tuple)) and len(item) == 2:
                out[str(item[0])] = item[1]
            elif isinstance(item, str) and item.strip():
                # ["need_clean_data", "figures_required"] → 布尔标志
                out[item.strip()] = True
        return out
    if isinstance(value, str) and value.strip():
        return {value.strip(): True}
    return {}


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x) for x in value if str(x).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def task_spec_from_llm_dict(data: dict[str, Any], fallback_goal: str = "") -> TaskSpec:
    if not isinstance(data, dict):
        raise ValueError(f"任务解析结果必须是 JSON object，实际类型：{type(data).__name__}")

    goal = str(data.get("goal") or fallback_goal).strip() or fallback_goal
    deliverables = _as_str_list(data.get("deliverables"))
    acceptance = _as_dict(data.get("acceptance"))
    # 顶层布尔字段兼容
    for key in ("need_clean_data", "figures_required", "need_figures"):
        if key in data and data[key] is not None:
            acceptance.setdefault(key if key != "need_figures" else "figures_required", bool(data[key]))

    if data.get("need_figures") or "figures" in deliverables or "wordcloud" in deliverables:
        acceptance.setdefault("figures_required", True)
    if acceptance.get("need_clean_data") or "clean_data" in deliverables:
        acceptance.setdefault("need_clean_data", True)

    params = _as_dict(data.get("params"))
    params.setdefault("drop_duplicates", True)
    params.setdefault("positive_threshold", 4)

    task_id = _slugify(str(data.get("task_id") or goal[:40] or "llm_task"))
    report_title = str(data.get("report_title") or "数据分析报告")
    assumptions = _as_str_list(data.get("assumptions"))
    clarifications = _as_str_list(data.get("clarifications"))

    raw_parts = [
        f"# 任务：{goal[:80]}",
        "",
        "## 目标",
        goal,
        "",
        "## 期望产出",
        *[f"- {d}" for d in deliverables],
    ]
    if assumptions:
        raw_parts += ["", "## 假设", *[f"- {a}" for a in assumptions]]
    if clarifications:
        raw_parts += ["", "## 待澄清", *[f"- {c}" for c in clarifications]]

    return TaskSpec(
        task_id=task_id,
        goal=goal,
        deliverables=deliverables,
        acceptance=acceptance,
        params=params,
        report={"title": report_title, "assumptions": assumptions, "clarifications": clarifications},
        raw_path=None,
        raw_text="\n".join(raw_parts),
    )
