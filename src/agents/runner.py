from __future__ import annotations

from collections.abc import Iterator

from src.agents.planner import plan, write_answer, write_answer_iter
from src.agents.policy import guard_answer, load_policy, research_hints, tools_for
from src.tools.base import ToolContext
from src.tools.registry import registry

ANALYST_TOOLS = tools_for("analyst")
RESEARCHER_TOOLS = tools_for("researcher")


def pick_agent(question: str, requested: str = "auto") -> str:
    name = (requested or "auto").strip().lower()
    if name in {"researcher", "analyst"}:
        return name
    from src.agents.planner import _has

    return "researcher" if _has(question, research_hints()) else "analyst"


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
    max_rounds: int | None = None,
) -> Iterator[dict]:
    if attachments:
        ctx.attachments = attachments
    if history:
        ctx.history = history
    policy = load_policy(agent)
    tools = list(policy.tools)
    ctx.allowed_tools = tools
    ctx.agent_name = agent
    allowed = set(tools)
    observations: list[dict] = []
    traces: list[dict] = []
    rounds = max_rounds if max_rounds is not None else policy.max_rounds
    # always_tools：YAML 一直写着「必调」，但运行时从没执行过，只有启发式分支偶然满足
    always = [t for t in (policy.always_tools or ()) if t in allowed]

    for idx in range(rounds):
        calls = plan(question, observations, ctx)
        if not calls:
            break
        if idx == 0 and always:
            missing = [t for t in always if t not in {c["id"] for c in calls}]
            if missing:
                # 放在最前面：后面的工具（如行情）常常依赖它先确定标的
                calls = [{"id": t, "args": {}} for t in missing] + calls
        for call in calls:
            payload, trace = _run_one(call, ctx, allowed)
            observations.append(payload)
            traces.append(trace)
            yield {"type": "tool", **trace, "agent": agent}

    if stream_tokens:
        chunks: list[str] = []
        cites: list[dict] = []
        for piece, cites in write_answer_iter(question, observations, agent=agent, ctx=ctx):
            chunks.append(piece)
            yield {"type": "token", "text": piece, "agent": agent}
        answer = "".join(chunks) if chunks else write_answer(question, observations, agent=agent, ctx=ctx)[0]
    else:
        answer, cites = write_answer(question, observations, agent=agent, ctx=ctx)
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
