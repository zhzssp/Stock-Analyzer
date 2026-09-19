from __future__ import annotations

from src.agents.reviewer import reviews_payload
from src.tools.base import ToolContext, ToolResult, ToolSpec
from src.tools.registry import registry


def watch_review(args: dict, ctx: ToolContext) -> ToolResult:
    if ctx.db is None:
        return ToolResult(ok=False, error="没有数据库", source="watch_review", cite="复盘")
    payload = reviews_payload(ctx.db, ctx.user_id)
    code = str(args.get("code") or "").strip()
    if code:
        code6 = code.split(".")[0][-6:]
        items = [x for x in payload["items"] if x.get("code6") == code6 or code in (x.get("code6") or "")]
        pending = [x for x in items if x.get("review_status") in {"pending", "deferred"}]
        done = [x for x in items if x.get("review_status") not in {"pending", "deferred"}]
        payload = {**payload, "items": items, "pending": pending, "done": done}
    return ToolResult(ok=True, data=payload, source="watch_review", cite="次日复盘")


registry.register(
    ToolSpec(
        "watch_review",
        "次日复盘",
        "compute",
        "读取盯盘命中的次日复盘标签：待复盘 / 同向 / 反向 / 波动不足 / 不按涨跌。只读，不改规则。",
        {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "question": {"type": "string"},
            },
        },
    ),
    watch_review,
)
