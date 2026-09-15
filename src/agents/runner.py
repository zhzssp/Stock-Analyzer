from __future__ import annotations

from collections.abc import Iterator

from src.agents.planner import plan, write_answer, write_answer_iter
from src.tools.base import ToolContext
from src.tools.registry import registry

ANALYST_TOOLS = [
    "excel_parse",
    "warehouse_get",
    "market_fetch",
    "quote",
    "company_profile",
    "holders_flow",
    "finance_snapshot",
    "universe",
    "query_run",
    "excel_list",
    "excel_read",
    "excel_diff",
    "capital_flow",
    "corp_events",
    "bottom",
    "taxonomy_lookup",
    "fund_holding",
    "futures_map",
    "export_share",
]

RESEARCHER_TOOLS = [
    "universe",
    "quote",
    "company_profile",
    "capital_flow",
    "corp_events",
    "bottom",
    "excel_list",
    "market_fetch",
    "warehouse_get",
    "web_finance_search",
    "futures_quote",
    "futures_map",
    "policy_news",
    "fund_holding",
    "taxonomy_lookup",
]


def pick_agent(question: str, requested: str = "auto") -> str:
    name = (requested or "auto").strip().lower()
    if name in {"researcher", "analyst"}:
        return name
    from src.agents.planner import RESEARCH_HINTS, _has

    return "researcher" if _has(question, RESEARCH_HINTS) else "analyst"


def _run_one(call: dict, ctx: ToolContext, allowed: set[str]) -> tuple[dict, dict]:
    tool_id = call["id"]
    args = call.get("args") or {}
    if tool_id not in allowed:
        payload = {
            "id": tool_id,
            "args": args,
            "ok": False,
            "error": f"未授权 Tool: {tool_id}",
            "source": "whitelist",
            "cite": tool_id,
        }
        return payload, {"id": tool_id, "ok": False, "cite": tool_id, "error": payload["error"]}
    result = registry.run(tool_id, args, ctx)
    payload = {"id": tool_id, "args": args, **result.to_dict()}
    trace = {"id": tool_id, "ok": result.ok, "cite": result.cite, "error": result.error}
    return payload, trace


def iter_agent(
    question: str,
    ctx: ToolContext,
    *,
    agent: str = "analyst",
    attachments: list[dict] | None = None,
    history: list[dict] | None = None,
    stream_tokens: bool = False,
    max_rounds: int = 3,
) -> Iterator[dict]:
    if attachments:
        ctx.attachments = attachments
    if history:
        ctx.history = history
    tools = RESEARCHER_TOOLS if agent == "researcher" else ANALYST_TOOLS
    ctx.allowed_tools = list(tools)
    allowed = set(tools)
    observations: list[dict] = []
    traces: list[dict] = []

    for _ in range(max_rounds):
        calls = plan(question, observations, ctx)
        if not calls:
            break
        for call in calls:
            payload, trace = _run_one(call, ctx, allowed)
            observations.append(payload)
            traces.append(trace)
            yield {"type": "tool", **trace, "agent": agent}
        if not calls:
            break

    if stream_tokens:
        chunks: list[str] = []
        cites: list[dict] = []
        for piece, cites in write_answer_iter(question, observations):
            chunks.append(piece)
            yield {"type": "token", "text": piece, "agent": agent}
        answer = "".join(chunks) if chunks else write_answer(question, observations)[0]
    else:
        answer, cites = write_answer(question, observations)
        yield {"type": "token", "text": answer, "agent": agent}

    yield {
        "type": "done",
        "answer": answer,
        "cites": cites,
        "tools": traces,
        "agent": agent,
    }


def collect_agent(
    question: str,
    ctx: ToolContext,
    *,
    agent: str = "analyst",
    attachments: list[dict] | None = None,
    history: list[dict] | None = None,
) -> dict:
    final = {"answer": "", "cites": [], "tools": [], "agent": agent}
    for event in iter_agent(question, ctx, agent=agent, attachments=attachments, history=history, stream_tokens=False):
        if event.get("type") == "done":
            final = {k: event[k] for k in ("answer", "cites", "tools", "agent")}
    return final
