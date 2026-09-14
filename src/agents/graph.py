from __future__ import annotations

from src.agents.runner import ANALYST_TOOLS, collect_agent, iter_agent
from src.tools.base import ToolContext


def run_analyst(question: str, ctx: ToolContext, attachments: list[dict] | None = None, history: list[dict] | None = None) -> dict:
    return collect_agent(question, ctx, agent="analyst", attachments=attachments, history=history)


def stream_analyst(question: str, ctx: ToolContext, attachments: list[dict] | None = None, history: list[dict] | None = None):
    yield from iter_agent(
        question,
        ctx,
        agent="analyst",
        attachments=attachments,
        history=history,
        stream_tokens=True,
    )
