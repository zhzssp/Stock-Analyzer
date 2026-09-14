from __future__ import annotations

from src.agents.runner import collect_agent, iter_agent
from src.platform.bus import bus
from src.tools.base import ToolContext


def _with_hits(question: str) -> str:
    hits = bus.recent("watch.hit", limit=8)
    if not hits:
        return question
    bits = []
    for msg in hits:
        payload = msg.get("payload") or {}
        bits.append(payload.get("title") or payload.get("job_key") or msg.get("id"))
    return question + "\n\n最近盯盘命中：" + "；".join(str(b) for b in bits if b)


def run_researcher(question: str, ctx: ToolContext, attachments: list[dict] | None = None, history: list[dict] | None = None) -> dict:
    return collect_agent(_with_hits(question), ctx, agent="researcher", attachments=attachments, history=history)


def stream_researcher(question: str, ctx: ToolContext, attachments: list[dict] | None = None, history: list[dict] | None = None):
    yield from iter_agent(
        _with_hits(question),
        ctx,
        agent="researcher",
        attachments=attachments,
        history=history,
        stream_tokens=True,
    )
