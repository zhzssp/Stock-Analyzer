from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from src.agents.planner import plan, write_answer
from src.tools.base import ToolContext
from src.tools.registry import registry


class AnalystState(TypedDict):
    question: str
    round: int
    pending: list[dict]
    observations: list[dict]
    answer: str
    cites: list[dict]
    traces: list[dict]
    finished: bool


def build_analyst(ctx: ToolContext):
    def plan_node(state: AnalystState) -> dict[str, Any]:
        if state["round"] >= 3:
            return {"pending": [], "finished": True}
        calls = plan(state["question"], state["observations"], ctx)
        return {"pending": calls, "finished": not calls}

    def act_node(state: AnalystState) -> dict[str, Any]:
        observations = list(state["observations"])
        traces = list(state["traces"])
        for call in state["pending"]:
            result = registry.run(call["id"], call.get("args") or {}, ctx)
            payload = {
                "id": call["id"],
                "args": call.get("args") or {},
                **result.to_dict(),
            }
            observations.append(payload)
            traces.append(
                {
                    "id": call["id"],
                    "ok": result.ok,
                    "cite": result.cite,
                    "error": result.error,
                }
            )
        return {
            "observations": observations,
            "traces": traces,
            "pending": [],
            "round": state["round"] + 1,
        }

    def write_node(state: AnalystState) -> dict[str, Any]:
        answer, cites = write_answer(state["question"], state["observations"])
        return {"answer": answer, "cites": cites, "finished": True}

    def route(state: AnalystState) -> str:
        if state["finished"] or state["round"] >= 3:
            return "write"
        if state["pending"]:
            return "act"
        return "write"

    graph = StateGraph(AnalystState)
    graph.add_node("plan", plan_node)
    graph.add_node("act", act_node)
    graph.add_node("write", write_node)
    graph.add_edge(START, "plan")
    graph.add_conditional_edges("plan", route, {"act": "act", "write": "write"})
    graph.add_edge("act", "plan")
    graph.add_edge("write", END)
    return graph.compile()


def run_analyst(question: str, ctx: ToolContext) -> dict:
    app = build_analyst(ctx)
    state = app.invoke(
        {
            "question": question,
            "round": 0,
            "pending": [],
            "observations": [],
            "answer": "",
            "cites": [],
            "traces": [],
            "finished": False,
        }
    )
    return {
        "answer": state["answer"],
        "cites": state["cites"],
        "tools": state["traces"],
        "agent": "analyst",
    }
