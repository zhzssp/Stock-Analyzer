from __future__ import annotations

from src.tools.base import ToolContext, ToolResult, ToolSpec
from src.tools.registry import registry
from src.tools.resolve import mentioned, resolve_codes, watch_instruments


def _pick(args: dict, ctx: ToolContext):
    codes = args.get("codes") or ([args["code"]] if args.get("code") else None)
    extras = watch_instruments(ctx)
    if codes:
        return resolve_codes(codes, ctx.market, extras)
    return mentioned(args.get("question") or args.get("name") or "", ctx.market, extras) or extras[:3]


def corp_disclosure(args: dict, ctx: ToolContext) -> ToolResult:
    insts = _pick(args, ctx)
    if not insts:
        return ToolResult(ok=False, error="没有可查询的标的", source="corp_disclosure", cite="公告/问董秘")
    rows = []
    for inst in insts:
        rows.append(
            {
                "name": inst.name,
                "code": inst.code_full,
                "announcements": ctx.market.announcements(inst),
                "interactive_qa": ctx.market.interactive_qa(inst),
                "cninfo_url": ctx.market.events(inst).get("cninfo_url"),
            }
        )
    return ToolResult(ok=True, data=rows, source="corp_disclosure", cite="公告 · 问董秘")


def limit_review(args: dict, ctx: ToolContext) -> ToolResult:
    insts = _pick(args, ctx)
    if not insts:
        return ToolResult(ok=False, error="没有可查询的标的", source="limit_review", cite="涨跌停/竞价")
    rows = []
    for inst in insts:
        rows.append(
            {
                "name": inst.name,
                "code": inst.code_full,
                "limit_perf": ctx.market.limit_performance(inst),
                "auction": ctx.market.auction(inst),
            }
        )
    return ToolResult(ok=True, data=rows, source="limit_review", cite="涨跌停表现 · 集合竞价")


def market_breadth(args: dict, ctx: ToolContext) -> ToolResult:
    limit = int(args.get("limit") or 6)
    pool = sorted(ctx.market.dragon_tiger_codes())
    watch = {i.code6 for i in watch_instruments(ctx)}
    hits = [c for c in pool if c in watch]
    return ToolResult(
        ok=True,
        data={
            "dragon_tiger_date": ctx.market.dragon_tiger_date(),
            "dragon_tiger_count": len(pool),
            "watch_on_board": hits,
            "sector_funds_industry": ctx.market.sector_funds_top("industry", limit),
            "sector_funds_concept": ctx.market.sector_funds_top("concept", limit),
        },
        source="market_breadth",
        cite="龙虎榜 · 板块资金",
    )


_schema = {
    "type": "object",
    "properties": {
        "code": {"type": "string"},
        "codes": {"type": "array", "items": {"type": "string"}},
        "question": {"type": "string"},
        "limit": {"type": "integer"},
    },
}

registry.register(
    ToolSpec("corp_disclosure", "公告与问董秘", "market", "交易所公告标题+链接、问董秘问答", _schema),
    corp_disclosure,
)
registry.register(
    ToolSpec("limit_review", "涨跌停复盘", "market", "涨跌停表现、集合竞价成交量", _schema),
    limit_review,
)
registry.register(
    ToolSpec("market_breadth", "盘面广度", "market", "今日龙虎榜概览、证监会行业/概念板块资金前列", {"type": "object", "properties": {"limit": {"type": "integer"}}}),
    market_breadth,
)
