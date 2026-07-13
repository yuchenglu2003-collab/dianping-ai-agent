from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv


PLACEHOLDER_KEYS = {
    "",
    "sk-your-key-here",
    "your-api-key",
    "changeme",
    "xxx",
}

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


@dataclass
class AuthResult:
    ok: bool
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    source: str = ""
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "source": self.source,
            "message": self.message,
            "model": self.model,
            "base_url": self.base_url,
            "api_key_set": bool(self.api_key),
        }


def _mask_key(key: str) -> str:
    if not key or len(key) < 8:
        return "****"
    return f"{key[:4]}****{key[-4:]}"


def _from_streamlit_secrets(key: str) -> str:
    """读取 Streamlit Cloud Secrets（本地无 secrets 时静默跳过）。"""
    try:
        import streamlit as st

        secrets = getattr(st, "secrets", None)
        if secrets is None:
            return ""
        if key in secrets:
            return str(secrets[key]).strip()
        # 兼容 [deepseek] api_key = "..."
        nested = secrets.get("deepseek") if hasattr(secrets, "get") else None
        if nested is not None:
            alias = {
                "DEEPSEEK_API_KEY": ("api_key", "DEEPSEEK_API_KEY"),
                "DEEPSEEK_BASE_URL": ("base_url", "DEEPSEEK_BASE_URL"),
                "DEEPSEEK_MODEL": ("model", "DEEPSEEK_MODEL"),
            }.get(key, ())
            for a in alias:
                if a in nested:
                    return str(nested[a]).strip()
    except Exception:
        return ""
    return ""


def resolve_api_credentials(
    *,
    project_root: Path | None = None,
    ui_api_key: str | None = None,
    config: dict[str, Any] | None = None,
) -> AuthResult:
    """解析 DeepSeek 密钥：UI > Secrets > DEEPSEEK_* > OPENAI_* > .env > config。"""
    root = project_root or Path.cwd()
    load_dotenv(root / ".env", override=False)

    llm_cfg = (config or {}).get("llm", {})
    base_url = (
        _from_streamlit_secrets("DEEPSEEK_BASE_URL")
        or os.getenv("DEEPSEEK_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or llm_cfg.get("base_url")
        or DEFAULT_BASE_URL
    )
    base_url = str(base_url).rstrip("/")
    if "deepseek.com" in base_url and not base_url.endswith(("/v1", "/beta")):
        base_url = base_url + "/v1"
    model = (
        _from_streamlit_secrets("DEEPSEEK_MODEL")
        or os.getenv("DEEPSEEK_MODEL")
        or os.getenv("OPENAI_MODEL")
        or llm_cfg.get("model")
        or DEFAULT_MODEL
    )

    candidates: list[tuple[str, str]] = []
    if ui_api_key and ui_api_key.strip():
        candidates.append(("ui", ui_api_key.strip()))
    secrets_key = _from_streamlit_secrets("DEEPSEEK_API_KEY")
    if secrets_key:
        candidates.append(("secrets", secrets_key))
    env_key = (
        os.getenv("DEEPSEEK_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    ).strip()
    if env_key:
        candidates.append(("env", env_key))
    cfg_key = str(llm_cfg.get("api_key") or "").strip()
    if cfg_key:
        candidates.append(("config", cfg_key))

    for source, key in candidates:
        if key.lower() in PLACEHOLDER_KEYS or key.startswith("sk-your"):
            continue
        return AuthResult(
            ok=True,
            api_key=key,
            base_url=base_url.rstrip("/"),
            model=model,
            source=source,
            message=f"已从 {source} 读取 DeepSeek 密钥 {_mask_key(key)}",
        )

    return AuthResult(
        ok=False,
        base_url=base_url.rstrip("/"),
        model=model,
        message=(
            "未配置有效 DeepSeek API 密钥。"
            "请在 UI 输入，或在 Streamlit Secrets / .env 设置 DEEPSEEK_API_KEY=sk-..."
        ),
    )


def require_api_key(
    *,
    project_root: Path | None = None,
    ui_api_key: str | None = None,
    config: dict[str, Any] | None = None,
    ping: bool = False,
) -> AuthResult:
    """强制要求密钥；可选 ping DeepSeek。"""
    cfg = config or {}
    result = resolve_api_credentials(
        project_root=project_root,
        ui_api_key=ui_api_key,
        config=cfg,
    )
    if not result.ok:
        return result

    if ping:
        try:
            from src.infra.llm_gateway import LLMGateway

            gw = LLMGateway(
                config=cfg.get("llm", {}),
                api_key=result.api_key or "",
                base_url=result.base_url,
            )
            probe = gw.probe_connectivity()
            result.base_url = str(probe.get("base_url") or result.base_url)
            if int(probe.get("status_code") or 0) in {401, 403}:
                return AuthResult(
                    ok=False,
                    api_key=result.api_key,
                    base_url=result.base_url,
                    model=result.model,
                    source=result.source,
                    message=(
                        f"网络可达（{result.base_url}），但 DeepSeek 密钥鉴权失败 "
                        f"HTTP {probe.get('status_code')}。"
                        "请到 https://platform.deepseek.com 重新复制 API Key。"
                    ),
                )
            gw.ping()
            result.message += f"；DeepSeek API 可达（{result.base_url}）"
        except Exception as e:
            return AuthResult(
                ok=False,
                api_key=result.api_key,
                base_url=result.base_url,
                model=result.model,
                source=result.source,
                message=f"密钥已配置，但 DeepSeek API 不可用: {e}",
            )
    return result
