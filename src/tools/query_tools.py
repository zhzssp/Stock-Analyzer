from __future__ import annotations

from src.market.client import resolve_instruments
from src.query.registry import registry as fields
from src.tools.base import ToolContext, ToolResult, ToolSpec
from src.tools.registry import registry
from src.tools.resolve import mentioned, watch_instruments


def query_run(args: dict, ctx: ToolContext) -> ToolResult:
    extras = watch_instruments(ctx)
    if args.get("codes"):
        insts = resolve_instruments(args["codes"], ctx.market)
    else:
        insts = mentioned(args.get("question") or "", ctx.market, extras) or extras
    if not insts:
        return ToolResult(ok=False, error="自选为空，也没有提到具体股票", source="query_run", cite="查询引擎")
    keys = args.get("fields") or fields.default_keys()
    cards = {}
    if ctx.db is not None:
        from src.models import WatchItem
        from src.query.cards import card_dict

        cards = {i.code6: card_dict(i) for i in ctx.db.query(WatchItem).filter_by(user_id=ctx.user_id).all()}
    writer = ""
    if ctx.db is not None:
        from src.models import User

        user = ctx.db.get(User, ctx.user_id)
        writer = user.username if user else ""
    rows = ctx.engine.run(
        insts,
        keys,
        cards=cards,
        writer=writer,
        refresh_mode="cache",
        force_live=False,
    )
    compact = []
    keep = {"name", "code", "price", "pct", "industry", "holders", "yffy", "eps", "pe", "net", "as_of"}
    for row in rows[:40]:
        compact.append({k: row.get(k) for k in keep if k in row})
    return ToolResult(
        ok=True,
        data={"count": len(rows), "rows": compact},
        source="query_run",
        cite="查询引擎 · query_run",
    )


registry.register(
    ToolSpec(
        "query_run",
        "现查一张表",
        "compute",
        "对自选或指定代码跑图 1 字段查询（内部 QueryEngine）",
        {
            "type": "object",
            "properties": {
                "codes": {"type": "array", "items": {"type": "string"}},
                "question": {"type": "string"},
                "fields": {"type": "array", "items": {"type": "string"}},
            },
        },
    ),
    query_run,
)
