from __future__ import annotations

from src.query.bottom import compute_bottom
from src.tools.base import ToolContext, ToolResult, ToolSpec
from src.tools.registry import registry
from src.tools.resolve import mentioned, resolve_codes, watch_instruments


def _pick(args: dict, ctx: ToolContext):
    codes = args.get("codes") or ([args["code"]] if args.get("code") else None)
    extras = watch_instruments(ctx)
    if codes:
        return resolve_codes(codes, ctx.market, extras)
    return mentioned(args.get("question") or args.get("name") or "", ctx.market, extras) or extras[:1]


def capital_flow(args: dict, ctx: ToolContext) -> ToolResult:
    insts = _pick(args, ctx)
    if not insts:
        return ToolResult(ok=False, error="没有可查询的标的", source="capital_flow", cite="资金流")
    rows = []
    for inst in insts:
        series = ctx.market.capital_flow(inst)
        nums = [float(x["net_in"]) for x in series if x.get("net_in") not in (None, "")]
        latest = nums[-1] if nums else None
        mean = sum(nums[:-1]) / max(len(nums) - 1, 1) if len(nums) > 1 else None
        last = series[-1] if series else {}
        rows.append(
            {
                "name": inst.name,
                "code": inst.code_full,
                "latest_net": latest,
                "mean_net": mean,
                "inflow": last.get("inflow"),
                "outflow": last.get("outflow"),
                "days": len(nums),
            }
        )
    return ToolResult(ok=True, data=rows, source="capital_flow", cite="资金流 · transaction")


def corp_events(args: dict, ctx: ToolContext) -> ToolResult:
    insts = _pick(args, ctx)
    if not insts:
        return ToolResult(ok=False, error="没有可查询的标的", source="corp_events", cite="公司事件")
    rows = []
    for inst in insts:
        ev = ctx.market.events(inst)
        rows.append({"name": inst.name, "code": inst.code_full, "cninfo_url": ev.get("cninfo_url"), **ev})
    return ToolResult(ok=True, data=rows, source="corp_events", cite="事件 · 分红/增发/解禁")


def bottom(args: dict, ctx: ToolContext) -> ToolResult:
    insts = _pick(args, ctx)
    if not insts:
        return ToolResult(ok=False, error="没有可查询的标的", source="bottom", cite="底部")
    rows = []
    for inst in insts:
        quote = ctx.market.quote(inst)
        calc = compute_bottom(ctx.market.history(inst), quote.get("p"))
        rows.append({"name": inst.name, "code": inst.code_full, "price": quote.get("p"), **calc})
    return ToolResult(ok=True, data=rows, source="bottom", cite="日线 · 底/顶/目标卖价")


_schema = {
    "type": "object",
    "properties": {
        "code": {"type": "string"},
        "codes": {"type": "array", "items": {"type": "string"}},
        "question": {"type": "string"},
    },
}

registry.register(ToolSpec("capital_flow", "个股资金流", "market", "查询资金净流入及近窗均值", _schema), capital_flow)
registry.register(ToolSpec("corp_events", "公司事件", "market", "查询分红、增发、解禁", _schema), corp_events)
registry.register(ToolSpec("bottom", "底部估值", "compute", "用日线计算近1年底、长窗底、顶、离底%、目标卖价", _schema), bottom)
