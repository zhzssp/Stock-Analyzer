from __future__ import annotations

from src.agents.runner import collect_agent, iter_agent
from src.agents.policy import load_policy
from src.platform.bus import bus
from src.tools.base import ToolContext


def _with_context(question: str, ctx: ToolContext | None = None) -> str:
    policy = load_policy("researcher")
    extra: list[str] = []
    if policy.inject_watch_hits:
        hits = bus.recent("watch.hit", limit=8)
        bits = []
        for msg in hits:
            payload = msg.get("payload") or {}
            bits.append(payload.get("title") or payload.get("job_key") or msg.get("id"))
        if bits:
            extra.append("最近盯盘命中：" + "；".join(str(b) for b in bits if b))
    if policy.inject_today_queue and ctx is not None and ctx.db is not None:
        from src.agents.queue import today_queue

        queue = today_queue(ctx.db, ctx.user_id)
        if queue:
            extra.append(
                "今日该看："
                + "；".join(f"{q.get('title')}（{q.get('code6') or ''}）" for q in queue[:12])
            )
    if ctx is not None and ctx.db is not None:
        from src.agents.reviewer import recent_review_lines

        reviews = recent_review_lines(ctx.db, ctx.user_id)
        if reviews:
            extra.append("次日复盘：" + "；".join(reviews))
    if not extra:
        return question
    return question + "\n\n" + "\n".join(extra)


def run_researcher(question: str, ctx: ToolContext, attachments: list[dict] | None = None, history: list[dict] | None = None) -> dict:
    return collect_agent(_with_context(question, ctx), ctx, agent="researcher", attachments=attachments, history=history)


def stream_researcher(question: str, ctx: ToolContext, attachments: list[dict] | None = None, history: list[dict] | None = None):
    yield from iter_agent(
        _with_context(question, ctx),
        ctx,
        agent="researcher",
        attachments=attachments,
        history=history,
        stream_tokens=True,
    )
