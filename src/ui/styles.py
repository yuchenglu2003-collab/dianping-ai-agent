"""UI 样式：点评数析品牌构图。"""

from __future__ import annotations

APP_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@500;700&family=Noto+Sans+SC:wght@400;500;600&display=swap');

:root {
  --ink: #1a1612;
  --ink-soft: #5c534a;
  --paper: #f7f3eb;
  --paper-2: #efe8dc;
  --line: rgba(26, 22, 18, 0.12);
  --brand: #ffc300;
  --brand-deep: #e6a800;
  --ok: #2f6b4f;
  --warn: #9a4a1c;
  --radius: 2px;
}

html, body, [data-testid="stAppViewContainer"] {
  font-family: "Noto Sans SC", "PingFang SC", sans-serif;
  color: var(--ink);
}

[data-testid="stAppViewContainer"] {
  background:
    radial-gradient(1200px 600px at 12% -10%, rgba(255, 195, 0, 0.28), transparent 55%),
    radial-gradient(900px 500px at 100% 0%, rgba(255, 230, 150, 0.22), transparent 50%),
    linear-gradient(180deg, #fbf8f1 0%, var(--paper) 42%, #f3eee4 100%);
}

[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { visibility: hidden; height: 0; }
#MainMenu, footer { visibility: hidden; }

.block-container {
  max-width: 760px !important;
  padding-top: 2.4rem !important;
  padding-bottom: 4rem !important;
}

/* —— Brand hero —— */
.dx-hero {
  margin: 0 0 2rem 0;
  animation: dx-rise 0.7s ease-out both;
}
.dx-brand {
  font-family: "Noto Serif SC", "Songti SC", serif;
  font-weight: 700;
  font-size: clamp(2.4rem, 6vw, 3.4rem);
  line-height: 1.05;
  letter-spacing: 0.04em;
  color: var(--ink);
  margin: 0;
}
.dx-brand span {
  display: inline-block;
  border-bottom: 6px solid var(--brand);
  padding-bottom: 0.08em;
  animation: dx-underline 0.9s ease-out 0.2s both;
}
.dx-lead {
  margin: 0.9rem 0 0 0;
  font-size: 1.02rem;
  line-height: 1.55;
  color: var(--ink-soft);
  max-width: 34em;
}

.dx-status {
  margin: 0.85rem 0 0 0;
  font-size: 0.86rem;
  color: var(--ink-soft);
  letter-spacing: 0.02em;
}
.dx-status.ok { color: var(--ok); }
.dx-status.warn { color: var(--warn); }

/* —— Sections: one job each —— */
.dx-section {
  margin: 1.75rem 0 0.55rem 0;
  animation: dx-rise 0.65s ease-out both;
}
.dx-section:nth-of-type(2) { animation-delay: 0.08s; }
.dx-label {
  font-family: "Noto Serif SC", serif;
  font-size: 1.2rem;
  font-weight: 700;
  margin: 0;
  color: var(--ink);
}
.dx-hint {
  margin: 0.25rem 0 0.7rem 0;
  font-size: 0.9rem;
  color: var(--ink-soft);
}

/* —— Inputs —— */
[data-testid="stFileUploader"] {
  background: rgba(255, 255, 255, 0.45);
  border: 1.5px dashed var(--line);
  border-radius: var(--radius);
  padding: 0.6rem 0.8rem 0.2rem;
  transition: border-color 0.2s ease, background 0.2s ease;
}
[data-testid="stFileUploader"]:hover {
  border-color: var(--brand-deep);
  background: rgba(255, 255, 255, 0.7);
}
[data-testid="stFileUploader"] section {
  padding: 0.4rem 0 !important;
}
[data-testid="stFileUploader"] label,
[data-testid="stFileUploader"] small,
[data-testid="stFileUploader"] [data-testid="stMarkdownContainer"] p {
  color: var(--ink-soft) !important;
}
[data-testid="stFileUploaderDropzone"] {
  background: transparent !important;
  border: none !important;
}

div[data-testid="stTextArea"] textarea {
  min-height: 150px !important;
  background: rgba(255, 255, 255, 0.55) !important;
  border: 1.5px solid var(--line) !important;
  border-radius: var(--radius) !important;
  color: var(--ink) !important;
  font-family: "Noto Sans SC", sans-serif !important;
  font-size: 0.98rem !important;
  line-height: 1.55 !important;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}
div[data-testid="stTextArea"] textarea:focus {
  border-color: var(--brand-deep) !important;
  box-shadow: 0 0 0 3px rgba(255, 195, 0, 0.28) !important;
}

/* —— Mode —— */
.dx-mode-wrap {
  margin-top: 1.25rem;
  animation: dx-rise 0.65s ease-out 0.12s both;
}
div[data-testid="stRadio"] > label {
  display: none !important;
}
div[data-testid="stRadio"] [role="radiogroup"] {
  gap: 0.55rem !important;
  flex-wrap: wrap !important;
}
div[data-testid="stRadio"] label[data-baseweb="radio"] {
  background: rgba(255,255,255,0.4);
  border: 1px solid var(--line);
  border-radius: var(--radius);
  padding: 0.35rem 0.75rem !important;
  margin: 0 !important;
}
div[data-testid="stRadio"] label[data-baseweb="radio"]:has(input:checked) {
  background: rgba(255, 195, 0, 0.35);
  border-color: var(--brand-deep);
}

/* —— CTA —— */
.dx-cta {
  margin-top: 1.4rem;
  animation: dx-rise 0.65s ease-out 0.18s both;
}
div[data-testid="stButton"] > button[kind="primary"],
div[data-testid="stButton"] > button {
  font-family: "Noto Sans SC", sans-serif !important;
  font-weight: 600 !important;
  letter-spacing: 0.06em !important;
  border-radius: var(--radius) !important;
  border: none !important;
  min-height: 3rem !important;
  transition: transform 0.18s ease, filter 0.18s ease !important;
}
div[data-testid="stButton"] > button[kind="primary"] {
  background: var(--ink) !important;
  color: var(--brand) !important;
}
div[data-testid="stButton"] > button[kind="primary"]:hover {
  filter: brightness(1.08);
  transform: translateY(-1px);
}
div[data-testid="stButton"] > button[kind="primary"]:disabled {
  opacity: 0.45 !important;
  transform: none !important;
}

/* secondary small actions */
.dx-tools {
  margin-top: 0.55rem;
}
.dx-tools div[data-testid="stButton"] > button {
  background: transparent !important;
  color: var(--ink-soft) !important;
  border: 1px solid var(--line) !important;
  min-height: 2.3rem !important;
  font-weight: 500 !important;
}

/* —— Report —— */
.dx-report-head {
  font-family: "Noto Serif SC", serif;
  font-size: 1.55rem;
  font-weight: 700;
  margin: 2rem 0 0.8rem;
  padding-top: 1rem;
  border-top: 1px solid var(--line);
}

@keyframes dx-rise {
  from { opacity: 0; transform: translateY(10px); }
  to { opacity: 1; transform: translateY(0); }
}
@keyframes dx-underline {
  from { border-bottom-color: transparent; }
  to { border-bottom-color: var(--brand); }
}

@media (max-width: 640px) {
  .block-container { padding-top: 1.4rem !important; }
  .dx-brand { font-size: 2.15rem; }
}
"""


def inject_styles() -> None:
    import streamlit as st

    st.markdown(f"<style>{APP_CSS}</style>", unsafe_allow_html=True)
