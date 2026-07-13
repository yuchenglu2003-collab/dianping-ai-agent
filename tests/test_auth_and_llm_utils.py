from src.agent.auth_gate import resolve_api_credentials
from src.agent.task_parser import task_spec_from_llm_dict
from src.infra.llm_gateway import _parse_json_content, normalize_base_url
from src.task_spec import TaskSpec


def test_auth_rejects_missing_key(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_BASE_URL", raising=False)
    (tmp_path / ".env").write_text("", encoding="utf-8")
    result = resolve_api_credentials(project_root=tmp_path, config={"llm": {}})
    assert result.ok is False


def test_auth_accepts_ui_key(tmp_path, monkeypatch):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = resolve_api_credentials(
        project_root=tmp_path,
        ui_api_key="sk-test1234567890abcd",
        config={"llm": {"model": "deepseek-chat"}},
    )
    assert result.ok is True
    assert result.source == "ui"
    assert result.model == "deepseek-chat"


def test_auth_prefers_deepseek_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-deepseek-real-key-xxxx")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    result = resolve_api_credentials(project_root=tmp_path, config={"llm": {}})
    assert result.ok is True
    assert result.source == "env"
    assert result.base_url.endswith("/v1")


def test_normalize_deepseek_url():
    assert normalize_base_url("https://api.deepseek.com") == "https://api.deepseek.com/v1"
    assert normalize_base_url("https://api.deepseek.com/v1") == "https://api.deepseek.com/v1"


def test_parse_json_content_with_fence():
    raw = '```json\n{"goal": "清洗", "deliverables": ["report"]}\n```'
    data = _parse_json_content(raw)
    assert data["goal"] == "清洗"


def test_task_spec_placeholder():
    t = TaskSpec(task_id="x", goal="做词云")
    assert t.goal == "做词云"


def test_task_spec_accepts_list_shaped_acceptance():
    """DeepSeek 有时把 acceptance 输出成字符串列表，不能直接 dict()。"""
    spec = task_spec_from_llm_dict(
        {
            "goal": "清洗并做词云",
            "deliverables": ["clean_data", "wordcloud", "report"],
            "acceptance": ["need_clean_data", "figures_required"],
            "params": [{"drop_duplicates": True}],
        },
        fallback_goal="fallback",
    )
    assert spec.acceptance["need_clean_data"] is True
    assert spec.acceptance["figures_required"] is True
    assert spec.params["drop_duplicates"] is True
