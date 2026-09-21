from __future__ import annotations

import json
from typing import Any, Iterator

import httpx

from src.config import settings

DEEPSEEK_BASE = "https://api.deepseek.com/v1"
DEEPSEEK_CHAT = "deepseek-flash"


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
) -> dict[str, Any] | None:
    """OpenAI-compatible Chat Completions. Default vendor is DeepSeek."""
    if not llm_available():
        return None
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
        return resp.json()["choices"][0]["message"]
    except Exception:
        return None


def chat_completions_stream(messages: list[dict]) -> Iterator[str]:
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
    except Exception:
        return
