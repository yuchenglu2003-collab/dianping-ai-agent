"""点评数析 — 数据分析 Agent 交互界面。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

# Streamlit Cloud 以 src/ui/app.py 为入口时，需把仓库根目录加入 path
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import streamlit as st

from src.agent.auth_gate import require_api_key
from src.agent.orchestrator import Orchestrator
from src.agent.run_loop import run_with_progress
from src.agent.state import AgentState
from src.config_loader import load_config
from src.task_spec import TaskSpec
from src.ui.helpers import save_uploaded_files
from src.ui.styles import inject_styles


def project_root() -> Path:
    return _ROOT


def init_page() -> None:
    st.set_page_config(
        page_title="点评数析",
        page_icon="◧",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    inject_styles()


def _render_report_with_assets(report_path: Path, content: str) -> None:
    bundle_dir = report_path.parent
    import re

    blocks = re.split(r"\n(?=### )", content)
    for block in blocks:
        if not block.strip():
            continue
        html_link = re.search(r"\[点击查看交互图表\]\((assets/[^)]+)\)", block)
        img = re.search(r"!\[([^\]]*)\]\((assets/[^)]+)\)", block)
        if img:
            text_before = block[: img.start()].strip()
            if text_before:
                st.markdown(text_before)
            img_path = bundle_dir / img.group(2)
            if img_path.exists():
                st.image(str(img_path), caption=img.group(1) or None, use_container_width=True)
            continue
        if html_link:
            text_before = block[: html_link.start()].strip()
            if text_before:
                st.markdown(text_before)
            html_path = bundle_dir / html_link.group(1)
            if html_path.exists():
                st.components.v1.html(html_path.read_text(encoding="utf-8"), height=420, scrolling=True)
            continue
        st.markdown(block)


def main() -> None:
    init_page()
    root = project_root()
    os.environ.setdefault("MPLCONFIGDIR", str(root / ".mplconfig"))
    os.environ.setdefault("MPLBACKEND", "Agg")
    (root / ".mplconfig").mkdir(parents=True, exist_ok=True)

    try:
        if "DEEPSEEK_API_KEY" in st.secrets:
            os.environ.setdefault("DEEPSEEK_API_KEY", str(st.secrets["DEEPSEEK_API_KEY"]))
        if "DEEPSEEK_BASE_URL" in st.secrets:
            os.environ.setdefault("DEEPSEEK_BASE_URL", str(st.secrets["DEEPSEEK_BASE_URL"]))
        if "DEEPSEEK_MODEL" in st.secrets:
            os.environ.setdefault("DEEPSEEK_MODEL", str(st.secrets["DEEPSEEK_MODEL"]))
    except Exception:
        pass

    config = load_config(project_root=root)
    upload_root = root / "data" / "uploads"
    upload_root.mkdir(parents=True, exist_ok=True)

    auth = require_api_key(project_root=root, config=config, ping=False)

    # —— 首屏：品牌 + 上传 + 任务 ——
    st.markdown(
        """
        <div class="dx-hero">
          <h1 class="dx-brand"><span>点评数析</span></h1>
          <p class="dx-lead">上传商家数据，用一句话说明要做什么。Agent 会理解任务、跑分析并写出报告。</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if auth.ok:
        st.markdown(
            f'<p class="dx-status ok">DeepSeek 已就绪 · {auth.model}</p>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<p class="dx-status warn">尚未配置 API 密钥：本地写入 .env 的 DEEPSEEK_API_KEY，云端用 Streamlit Secrets</p>',
            unsafe_allow_html=True,
        )

    st.markdown(
        """
        <div class="dx-section">
          <p class="dx-label">数据集</p>
          <p class="dx-hint">支持 CSV / TSV / Excel / Parquet，可多文件</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    uploaded = st.file_uploader(
        "数据集",
        type=["csv", "tsv", "xlsx", "xls", "parquet"],
        accept_multiple_files=True,
        label_visibility="collapsed",
    )

    file_names: list[str] = []
    if uploaded:
        file_names = [f.name for f in uploaded]
    elif st.session_state.get("saved_data_names"):
        file_names = list(st.session_state["saved_data_names"])
    if file_names:
        st.caption("已选：" + "、".join(file_names))

    st.markdown(
        """
        <div class="dx-section">
          <p class="dx-label">任务描述</p>
          <p class="dx-hint">直接写你想看的结论，例如清洗、评分分布、词云、漏斗或销量预测</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    task_text = st.text_area(
        "任务要求",
        placeholder="对评论做清洗，画出评分分布和时序趋势，再做词云；最后写一份简短分析报告。",
        height=160,
        label_visibility="collapsed",
    )

    st.markdown('<div class="dx-mode-wrap"></div>', unsafe_allow_html=True)
    default_react = (config.get("orchestrator", {}) or {}).get("mode", "plan_execute") == "react"
    mode_label = st.radio(
        "Agent 模式",
        options=["一次规划", "边想边做"],
        index=1 if default_react else 0,
        horizontal=True,
        help="一次规划：先生成完整步骤再执行。边想边做：ReAct，每步思考后调用工具。",
        label_visibility="collapsed",
    )
    agent_mode = "react" if mode_label == "边想边做" else "plan_execute"

    st.markdown('<div class="dx-cta"></div>', unsafe_allow_html=True)
    can_run = bool(auth.ok)
    run = st.button("开始分析", type="primary", use_container_width=True, disabled=not can_run)

    if auth.ok:
        st.markdown('<div class="dx-tools"></div>', unsafe_allow_html=True)
        if st.button("测试 DeepSeek 连接", use_container_width=True):
            test = require_api_key(project_root=root, config=config, ping=True)
            if test.ok:
                st.success(test.message)
            else:
                st.error(test.message)

    data_paths: list[Path] = []
    if uploaded:
        data_paths = save_uploaded_files(uploaded, upload_root)
        st.session_state["saved_data_paths"] = [str(p) for p in data_paths]
        st.session_state["saved_data_names"] = [p.name for p in data_paths]
    elif st.session_state.get("saved_data_paths"):
        data_paths = [Path(p) for p in st.session_state["saved_data_paths"]]

    if run:
        if not auth.ok:
            st.error("未检测到环境中的 DeepSeek API 密钥")
            st.stop()
        if not data_paths:
            st.error("请先上传数据集")
            st.stop()
        if not task_text.strip():
            st.error("请填写任务描述")
            st.stop()

        placeholder = TaskSpec(
            task_id="pending_llm_parse",
            goal=task_text.strip(),
            deliverables=["report"],
            raw_text=task_text.strip(),
        )

        progress_bar = st.progress(0, text="准备开始...")
        status_box = st.empty()

        def on_progress(pct: float, message: str) -> None:
            progress_bar.progress(pct, text=message)
            status_box.info(message)

        orch = Orchestrator.start_with_spec(
            data=[str(p) for p in data_paths],
            task_spec=placeholder,
            project_root=root,
            api_key=auth.api_key,
        )
        state = run_with_progress(
            orch,
            on_progress=on_progress,
            raw_task_text=task_text.strip(),
            agent_mode=agent_mode,
        )

        if state.status == "DONE":
            progress_bar.progress(1.0, text="分析完成")
            status_box.success("分析完成，报告已生成。")
        elif state.status == "BLOCKED":
            progress_bar.progress(1.0, text="已阻断")
            status_box.error("缺少有效 API 密钥，无法启动 Agent。")
        else:
            progress_bar.progress(1.0, text=f"结束：{state.status}")
            err_msg = ""
            if state.errors:
                last = state.errors[-1]
                err_msg = last.get("error") or last.get("detail") or str(last)
            status_box.error(
                f"任务失败（{state.status}）：{err_msg}" if err_msg else f"任务结束：{state.status}"
            )
            if state.errors:
                with st.expander("错误详情", expanded=True):
                    st.json(state.errors)

        st.session_state["last_state"] = state.to_dict()
        st.session_state["last_report"] = state.artifacts.get("report")

    if st.session_state.get("last_report"):
        report_path = Path(st.session_state["last_report"])
        if report_path.exists():
            st.markdown('<p class="dx-report-head">分析报告</p>', unsafe_allow_html=True)
            content = report_path.read_text(encoding="utf-8")
            _render_report_with_assets(report_path, content)

            col1, col2 = st.columns(2)
            col1.download_button(
                "下载 Markdown 报告",
                data=content,
                file_name=report_path.name,
                mime="text/markdown",
                use_container_width=True,
            )

            state = AgentState.from_dict(st.session_state.get("last_state", {}))
            clean_path = state.artifacts.get("clean_data_download") or state.artifacts.get("clean_csv")
            if clean_path and Path(clean_path).exists():
                col2.download_button(
                    "下载清洗后数据",
                    data=Path(clean_path).read_bytes(),
                    file_name=Path(clean_path).name,
                    mime="text/csv",
                    use_container_width=True,
                )

            if state.llm_usage:
                with st.expander("LLM 用量"):
                    st.json(state.llm_usage)

            mapping_path = state.artifacts.get("column_mapping")
            if mapping_path and Path(mapping_path).exists():
                with st.expander("字段识别（原始列 → 标准字段）"):
                    st.json(json.loads(Path(mapping_path).read_text(encoding="utf-8")))

            react_path = state.artifacts.get("react_trace")
            if react_path and Path(react_path).exists():
                with st.expander("ReAct 轨迹（Thought / Action / Observation）"):
                    st.json(json.loads(Path(react_path).read_text(encoding="utf-8")))

            if state.status != "DONE":
                st.warning(f"任务状态：{state.status}")
                if state.errors:
                    with st.expander("错误详情"):
                        st.json(state.errors)


if __name__ == "__main__":
    main()
