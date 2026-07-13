"""大众点评数据分析 AI Agent — LLM 驱动交互界面。"""

from __future__ import annotations

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


def project_root() -> Path:
    return _ROOT


def init_page() -> None:
    st.set_page_config(
        page_title="数据分析 Agent",
        page_icon="📊",
        layout="centered",
        initial_sidebar_state="collapsed",
    )
    st.markdown(
        """
        <style>
        .block-container { max-width: 820px; padding-top: 2rem; }
        .stTextArea textarea { min-height: 140px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


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
    # 云端 Secrets → 环境变量（方便子模块统一读取）
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

    st.title("数据分析 Agent")
    st.caption("覆盖四周课程：评论清洗EDA/词云、归因与评分预测、漏斗RFM、销量预测。上传对应数据 + 选任务或自写要求。")

    CURRICULUM = {
        "自定义任务": "",
        "第一周：清洗 + EDA + 词云（用 data1/week1_reviews）": (
            "对大众点评评论数据做清洗（缺失/异常/去重），输出干净数据集；"
            "绘制门店数量与评分分布；做时序分析（评论量、评分、用户趋势与评论长度分布）；"
            "对评论分词并制作词云，给出高频词初步结论；最后写分析报告。"
        ),
        "第二周：归因 + 评分预测（用 data1/week1_reviews）": (
            "分析口味、服务、环境在好评中的占比，并分析评论长短与好评关系，输出归因报告；"
            "用评论文本做评分预测（TF-IDF + 朴素贝叶斯/随机森林/梯度提升对比准确率与F1）；"
            "给出模型对比表与结论报告。"
        ),
        "第三周：漏斗 + RFM（用 data2/week3_behavior）": (
            "基于用户行为日志计算 PV、UV、CTR、CVR、GMV、DAU/ARPU/ARPPU，绘制流量漏斗；"
            "构建 RFM 用户分层（重要价值/发展/保持/挽留等）并给出差异化运营策略；输出报告。"
        ),
        "第四周：销量预测与异常（用 data3/week4_sales）": (
            "分析门店销量与月度/价格关系，检测销量与单价异常；"
            "构建简易销量预测并对比门店销量，输出《门店销量预测与异常监控报告》。"
        ),
    }
    preset = st.selectbox("课程任务模板", list(CURRICULUM.keys()))
    preset_text = CURRICULUM[preset]

    # ---- 密钥：仅使用环境变量 / Streamlit Secrets / .env ----
    auth = require_api_key(project_root=root, config=config, ping=False)
    if auth.ok:
        st.caption(f"DeepSeek：{auth.message} · 模型：{auth.model}")
        if st.button("测试 DeepSeek 连接", use_container_width=True):
            test = require_api_key(project_root=root, config=config, ping=True)
            if test.ok:
                st.success(test.message)
            else:
                st.error(test.message)
    else:
        st.warning(
            auth.message
            + "（本地写入 .env 的 DEEPSEEK_API_KEY，云端在 Streamlit Secrets 配置）"
        )

    uploaded = st.file_uploader(
        "数据集",
        type=["csv", "tsv", "xlsx", "xls", "parquet"],
        accept_multiple_files=True,
    )

    task_text = st.text_area(
        "任务要求",
        value=preset_text,
        placeholder=(
            "例如：对评论数据做清洗，输出评分分布和时序趋势图，"
            "并做词云分析高频关键词；如有需要附上清洗后的数据。"
        ),
        height=180,
    )

    can_run = auth.ok
    run = st.button("开始分析", type="primary", use_container_width=True, disabled=not can_run)

    data_paths: list[Path] = []
    if uploaded:
        data_paths = save_uploaded_files(uploaded, upload_root)
        st.session_state["saved_data_paths"] = [str(p) for p in data_paths]
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
            st.error("请填写任务要求")
            st.stop()

        # 占位 TaskSpec，真正理解交给 LLM
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
        )

        if state.status == "DONE":
            progress_bar.progress(1.0, text="分析完成 ✓")
            status_box.success("分析完成，报告已由大模型生成。")
        elif state.status == "BLOCKED":
            progress_bar.progress(1.0, text="已阻断")
            status_box.error("缺少有效 API 密钥，无法启动 Agent。")
        else:
            progress_bar.progress(1.0, text=f"结束：{state.status}")
            err_msg = ""
            if state.errors:
                last = state.errors[-1]
                err_msg = last.get("error") or last.get("detail") or str(last)
            status_box.error(f"任务失败（{state.status}）：{err_msg}" if err_msg else f"任务结束：{state.status}")
            if state.errors:
                with st.expander("错误详情", expanded=True):
                    st.json(state.errors)

        st.session_state["last_state"] = state.to_dict()
        st.session_state["last_report"] = state.artifacts.get("report")

    if st.session_state.get("last_report"):
        report_path = Path(st.session_state["last_report"])
        if report_path.exists():
            st.divider()
            st.subheader("分析报告")
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

            if state.status != "DONE":
                st.warning(f"任务状态：{state.status}")
                if state.errors:
                    with st.expander("错误详情"):
                        st.json(state.errors)


if __name__ == "__main__":
    main()
