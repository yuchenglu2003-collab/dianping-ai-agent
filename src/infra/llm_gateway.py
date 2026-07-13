from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

import httpx

# DeepSeek 官方 Chat Completions
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-chat"


@dataclass
class LLMCallRecord:
    stage: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    ok: bool = True
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "latency_ms": self.latency_ms,
            "ok": self.ok,
            "error": self.error,
        }


def normalize_base_url(url: str) -> str:
    """DeepSeek 官方：https://api.deepseek.com 或 .../v1 均可，统一补到 /v1。"""
    raw = (url or DEFAULT_BASE_URL).rstrip("/")
    if "deepseek.com" in raw and not raw.endswith(("/v1", "/beta")):
        raw = f"{raw}/v1"
    return raw


def candidate_base_urls(primary: str) -> list[str]:
    primary = normalize_base_url(primary)
    alts = [primary]
    for u in (DEFAULT_BASE_URL, "https://api.deepseek.com"):
        if u not in alts:
            alts.append(u)
    return alts


class LLMGateway:
    """DeepSeek API Gateway（httpx 直连 /v1/chat/completions，不经 OpenAI SDK）。"""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        api_key: str = "",
        base_url: str | None = None,
    ):
        self.config = config or {}
        if not api_key:
            raise RuntimeError("LLMGateway 需要 API 密钥。请配置 DEEPSEEK_API_KEY。")
        self.api_key = api_key.strip()
        self.base_url = normalize_base_url(
            base_url or self.config.get("base_url") or DEFAULT_BASE_URL
        )
        self.model = self.config.get("model") or DEFAULT_MODEL
        self.temperature = float(self.config.get("temperature", 0.2))
        self.max_tokens = int(self.config.get("max_tokens", 4096))
        self.timeout = float(self.config.get("timeout_sec", 90))
        self.max_retries = int(self.config.get("max_retries", 2))
        self.json_mode = bool(self.config.get("json_mode", True))
        self.calls: list[LLMCallRecord] = []
        self._http = httpx.Client(
            timeout=httpx.Timeout(self.timeout, connect=20.0),
            trust_env=True,
            follow_redirects=True,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def ping(self) -> None:
        self.probe_connectivity()
        self.chat(
            [{"role": "user", "content": "只回复：OK"}],
            stage="ping",
            max_tokens=8,
            temperature=0,
        )

    def probe_connectivity(self) -> dict[str, Any]:
        """GET /models 探测 DeepSeek 是否可达。"""
        errors: list[str] = []
        for base in candidate_base_urls(self.base_url):
            url = f"{base.rstrip('/')}/models"
            try:
                resp = self._http.get(url, headers=self._headers())
                if resp.status_code in {200, 401, 403}:
                    self.base_url = base
                    out: dict[str, Any] = {
                        "ok": True,
                        "base_url": base,
                        "status_code": resp.status_code,
                    }
                    if resp.status_code != 200:
                        out["body"] = resp.text[:200]
                    return out
                errors.append(f"{url} -> HTTP {resp.status_code}: {resp.text[:120]}")
            except Exception as e:
                errors.append(f"{url} -> {type(e).__name__}: {e}")
        raise RuntimeError(
            "无法访问 DeepSeek API。"
            + "；".join(errors)
            + "。请检查网络/VPN/代理（HTTPS_PROXY），或在终端执行：curl -I https://api.deepseek.com"
        )

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        stage: str = "chat",
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict | None = None,
    ) -> str:
        model = model or self.model
        started = time.time()
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        last_error: Exception | None = None
        for base in candidate_base_urls(self.base_url):
            url = f"{base.rstrip('/')}/chat/completions"
            for attempt in range(self.max_retries + 1):
                try:
                    resp = self._http.post(url, headers=self._headers(), json=payload)
                    if resp.status_code in {401, 403}:
                        raise RuntimeError(
                            f"DeepSeek 鉴权失败 HTTP {resp.status_code}: {resp.text[:400]}"
                        )
                    if resp.status_code == 429:
                        if attempt < self.max_retries:
                            time.sleep(1.5 * (attempt + 1))
                            continue
                        raise RuntimeError(f"DeepSeek 限流 HTTP 429: {resp.text[:400]}")
                    if resp.status_code >= 400:
                        raise RuntimeError(
                            f"DeepSeek API 错误 HTTP {resp.status_code}: {resp.text[:500]}"
                        )
                    data = resp.json()
                    content = (
                        (data.get("choices") or [{}])[0]
                        .get("message", {})
                        .get("content")
                        or ""
                    )
                    usage = data.get("usage") or {}
                    self.base_url = base
                    self.calls.append(
                        LLMCallRecord(
                            stage=stage,
                            model=model,
                            prompt_tokens=int(usage.get("prompt_tokens") or 0),
                            completion_tokens=int(usage.get("completion_tokens") or 0),
                            latency_ms=int((time.time() - started) * 1000),
                            ok=True,
                        )
                    )
                    return content.strip()
                except RuntimeError as e:
                    # 鉴权/业务错误不换 endpoint 重试
                    msg = str(e).lower()
                    if "鉴权" in str(e) or "401" in msg or "403" in msg:
                        last_error = e
                        detail = _format_llm_error(e, base, model)
                        self.calls.append(
                            LLMCallRecord(
                                stage=stage,
                                model=model,
                                latency_ms=int((time.time() - started) * 1000),
                                ok=False,
                                error=detail,
                            )
                        )
                        raise RuntimeError(detail) from e
                    last_error = e
                    if attempt < self.max_retries and ("429" in msg or "限流" in str(e)):
                        continue
                    break
                except Exception as e:
                    last_error = e
                    if attempt < self.max_retries:
                        time.sleep(0.8 * (attempt + 1))
                        continue
                    break

        detail = _format_llm_error(last_error or RuntimeError("unknown"), self.base_url, model)
        self.calls.append(
            LLMCallRecord(
                stage=stage,
                model=model,
                latency_ms=int((time.time() - started) * 1000),
                ok=False,
                error=detail,
            )
        )
        raise RuntimeError(detail) from last_error

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        stage: str = "chat_json",
        model: str | None = None,
    ) -> dict[str, Any]:
        msgs = list(messages)
        if msgs and msgs[-1]["role"] == "user":
            msgs[-1] = {
                "role": "user",
                "content": msgs[-1]["content"] + "\n\n请只输出合法 JSON，不要 Markdown 代码块。",
            }
        try:
            raw = self.chat(
                msgs,
                stage=stage,
                model=model,
                response_format={"type": "json_object"} if self.json_mode else None,
            )
            return _parse_json_content(raw)
        except Exception:
            raw = self.chat(msgs, stage=stage, model=model, response_format=None)
            return _parse_json_content(raw)

    def usage_summary(self) -> dict[str, Any]:
        return {
            "calls": len(self.calls),
            "prompt_tokens": sum(c.prompt_tokens for c in self.calls),
            "completion_tokens": sum(c.completion_tokens for c in self.calls),
            "records": [c.to_dict() for c in self.calls],
        }


def _format_llm_error(exc: Exception, base_url: str, model: str) -> str:
    name = type(exc).__name__
    msg = str(exc) or name
    cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
    if cause and str(cause) not in msg:
        msg = f"{msg} | cause={cause}"

    lower = msg.lower()
    hints: list[str] = []
    if (
        "connection" in lower
        or "connect" in lower
        or "timeout" in lower
        or name in {"ConnectError", "ConnectTimeout", "ReadTimeout", "ProxyError"}
    ):
        hints.append("连不上 DeepSeek（常见：VPN/代理/防火墙）")
        hints.append("终端测试：curl -I https://api.deepseek.com")
        hints.append("若需代理，设置 HTTPS_PROXY 后重启 UI")
    elif "401" in msg or "403" in msg or "鉴权" in msg or "authentication" in lower:
        hints.append("密钥无效，请到 https://platform.deepseek.com 重新复制")
    elif "402" in msg or "insufficient" in lower or "balance" in lower:
        hints.append("账户余额不足")
    elif "429" in msg or "限流" in msg or "rate" in lower:
        hints.append("触发限流，请稍后重试")
    elif "model" in lower and ("not found" in lower or "does not exist" in lower):
        hints.append(f"模型名可能不对：当前 {model}，请用 deepseek-chat")

    hint_text = "；".join(hints)
    return f"DeepSeek 调用失败 [{name}] model={model} base_url={base_url}: {msg}" + (
        f" | 建议：{hint_text}" if hint_text else ""
    )


def _parse_json_content(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        raise ValueError("JSON 根节点必须是 object")
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            raise
        data = json.loads(m.group(0))
        if not isinstance(data, dict):
            raise ValueError("JSON 根节点必须是 object")
        return data
