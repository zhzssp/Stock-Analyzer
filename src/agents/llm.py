from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Iterator

import httpx

from src.config import settings

DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEEPSEEK_CHAT = "deepseek-flash"

LLM_ERR_BALANCE = "模型服务余额不足，请充值或更换 API Key 后重试。"
LLM_ERR_REQUEST = "模型请求失败，请稍后重试。"


@dataclass
class ChatResult:
    message: dict[str, Any] | None = None
    error: str | None = None


def llm_available() -> bool:
    return bool(settings.llm_api_key.strip())


def llm_supports_tools() -> bool:
    return "reasoner" not in (settings.llm_model or "").lower()


def llm_status() -> dict:
    return {
        "available": llm_available(),
        "provider": settings.llm_provider,
        "model": settings.llm_model,
        "base_url": _chat_base(),
        "tools": llm_supports_tools(),
    }


def llm_failure_message(exc: Exception | None = None, *, status_code: int | None = None, body: str = "") -> str:
    code = status_code
    text = (body or "").lower()
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        try:
            text = (exc.response.text or "").lower()
        except Exception:
            text = ""
    if code == 402 or "insufficient balance" in text or "余额不足" in text or "insufficient_balance" in text:
        return LLM_ERR_BALANCE
    return LLM_ERR_REQUEST


def _chat_base() -> str:
    raw = (settings.llm_base_url or "").strip().rstrip("/")
    if not raw:
        raw = DEEPSEEK_BASE if settings.llm_provider == "deepseek" else "https://api.openai.com/v1"
    if "deepseek.com" in raw and not raw.endswith("/v1"):
        return f"{raw}/v1"
    return raw


def chat_completions(
    messages: list[dict],
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
) -> ChatResult:
    """OpenAI-compatible Chat Completions. Default vendor is DeepSeek."""
    if not llm_available():
        return ChatResult()
    payload: dict[str, Any] = {
        "model": settings.llm_model or DEEPSEEK_CHAT,
        "messages": messages,
        # Flash 默认会开 thinking，既更贵也会在 Tool 多轮里要求回传 reasoning_content。
        "thinking": {"type": "disabled"},
    }
    if tools and llm_supports_tools():
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice
    try:
        resp = httpx.post(
            f"{_chat_base()}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=settings.llm_timeout,
        )
        resp.raise_for_status()
        return ChatResult(message=resp.json()["choices"][0]["message"])
    except httpx.HTTPStatusError as exc:
        return ChatResult(error=llm_failure_message(exc))
    except Exception:
        return ChatResult(error=LLM_ERR_REQUEST)


def chat_completions_stream(
    messages: list[dict],
    on_error: Callable[[str], None] | None = None,
) -> Iterator[str]:
    if not llm_available():
        return
    payload: dict[str, Any] = {
        "model": settings.llm_model or DEEPSEEK_CHAT,
        "messages": messages,
        "stream": True,
        "thinking": {"type": "disabled"},
    }
    try:
        with httpx.Client(timeout=settings.llm_timeout) as client:
            with client.stream(
                "POST",
                f"{_chat_base()}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if not line:
                        continue
                    if line.startswith("data:"):
                        data = line[5:].strip()
                    elif line.startswith("data: "):
                        data = line[6:].strip()
                    else:
                        continue
                    if data == "[DONE]":
                        break
                    try:
                        piece = json.loads(data)["choices"][0].get("delta", {}).get("content")
                    except Exception:
                        continue
                    if piece:
                        yield piece
    except httpx.HTTPStatusError as exc:
        if on_error:
            on_error(llm_failure_message(exc))
        return
    except Exception:
        if on_error:
            on_error(LLM_ERR_REQUEST)
        return
