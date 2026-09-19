from __future__ import annotations

from src.query.cards import card_dict
from src.models import WatchItem
from src.tools.base import ToolContext, ToolResult, ToolSpec
from src.tools.registry import registry
from src.tools.resolve import mentioned, resolve_codes, watch_instruments


def _pick(args: dict, ctx: ToolContext):
    codes = args.get("codes") or ([args["code"]] if args.get("code") else None)
    extras = watch_instruments(ctx)
    if codes:
        return resolve_codes(codes, ctx.market, extras)
    hits = mentioned(args.get("question") or args.get("name") or "", ctx.market, extras)
    return hits or extras


def watch_card(args: dict, ctx: ToolContext) -> ToolResult:
    insts = _pick(args, ctx)
    if not insts:
        return ToolResult(ok=False, error="没有可查询的标的", source="watch_card", cite="决策卡")
    rows = []
    for inst in insts:
        item = (
            ctx.db.query(WatchItem).filter_by(user_id=ctx.user_id, code6=inst.code6).first()
            if ctx.db is not None
            else None
        )
        card = card_dict(item) if item else {}
        filled = bool(
            card.get("thesis")
            or card.get("cost") is not None
            or card.get("buy_low") is not None
            or card.get("buy_high") is not None
            or card.get("reduce_price") is not None
            or card.get("invalid_if")
        )
        rows.append(
            {
                "name": inst.name,
                "code": inst.code_full,
                "filled": filled,
                **card,
            }
        )
    return ToolResult(ok=True, data=rows, source="watch_card", cite="决策卡")


registry.register(
    ToolSpec(
        "watch_card",
        "自选决策卡",
        "compute",
        "读取用户为自选填写的买区、减仓价、成本与持有逻辑；未填则标明未填",
        {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "codes": {"type": "array", "items": {"type": "string"}},
                "question": {"type": "string"},
            },
        },
    ),
    watch_card,
)
