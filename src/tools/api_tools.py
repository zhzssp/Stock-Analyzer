from __future__ import annotations

from src.tools.base import ToolContext, ToolResult, ToolSpec
from src.tools.registry import registry
from src.tools.resolve import mentioned, resolve_codes, watch_instruments

RESOURCES = ("quote", "profile", "holders", "finance", "history", "capital_flow", "events")


def _insts(args: dict, ctx: ToolContext):
    extras = watch_instruments(ctx)
    raw = args.get("codes") or ([args["code"]] if args.get("code") else None)
    if raw:
        return resolve_codes(raw, ctx.market, extras)
    return mentioned(args.get("question") or "", ctx.market, extras)


def _blank(value):
    if value in (None, "", "-", "—"):
        return None
    return value


def market_fetch(args: dict, ctx: ToolContext) -> ToolResult:
    resource = (args.get("resource") or args.get("method") or "").strip()
    if resource not in RESOURCES:
        return ToolResult(
            ok=False,
            error=f"resource 必须是 {', '.join(RESOURCES)}",
            source="market_fetch",
            cite="行情接口",
        )
    insts = _insts(args, ctx)
    if not insts:
        return ToolResult(ok=False, error="请提供 code / codes，或在问题里点名股票", source="market_fetch", cite="行情接口")

    source = "offline" if ctx.market.offline else ("sample" if ctx.market.sample_only else "live")
    rows = []
    for inst in insts[:12]:
        item = {"name": inst.name, "code": inst.code_full, "resource": resource, "source": source}
        if resource == "quote":
            q = ctx.market.quote(inst)
            item.update({"price": _blank(q.get("p")), "pct": _blank(q.get("pc")), "pe": _blank(q.get("pe")), "pb": _blank(q.get("sjl"))})
        elif resource == "profile":
            p = ctx.market.profile(inst)
            item.update({"industry": _blank(p.get("industry")), "concept": _blank(p.get("concept")), "business": _blank(p.get("business"))})
        elif resource == "holders":
            h = ctx.market.holders(inst)
            item.update({"holders": _blank(h.get("holders")), "holders_detail": h.get("holders_detail") or []})
        elif resource == "finance":
            f = ctx.market.finance(inst)
            item.update(
                {
                    "zgb": _blank(f.get("zgb")),
                    "ltgb": _blank(f.get("ysltag")),
                    "mgwfplr": _blank(f.get("mgwfplr")),
                    "yffy": _blank(f.get("yffy")),
                    "mgjzc": _blank(f.get("mgjzc")),
                    "eps": _blank(f.get("jbmgsy")),
                    "gross": _blank(f.get("xsmlv")),
                    "net": _blank(f.get("jlv")),
                }
            )
        elif resource == "history":
            bars = ctx.market.history(
                inst,
                adjust=args.get("adjust") or "n",
                start=args.get("start"),
                end=args.get("end"),
                limit=int(args.get("limit") or 40),
            )
            item.update({"count": len(bars), "bars": bars})
        elif resource == "capital_flow":
            series = ctx.market.capital_flow(inst)
            nums = [float(x["net_in"]) for x in series if x.get("net_in") not in (None, "")]
            latest = nums[-1] if nums else None
            mean = sum(nums[:-1]) / max(len(nums) - 1, 1) if len(nums) > 1 else None
            item.update({"latest_net": latest, "mean_net": mean, "days": len(nums), "series": series[-int(args.get("limit") or 10) :]})
        else:
            ev = ctx.market.events(inst)
            item.update(ev)
        rows.append(item)

    return ToolResult(
        ok=True,
        data={"resource": resource, "source": source, "rows": rows},
        source="market_fetch",
        cite=f"接口 · {resource} · {source}",
    )


registry.register(
    ToolSpec(
        "market_fetch",
        "带参查数",
        "market",
        "按 resource + 代码直接查行情/资料/股东/财务/日线/资金流/事件。离线用切片，正式 licence 走麦蕊实盘。",
        {
            "type": "object",
            "properties": {
                "resource": {"type": "string", "enum": list(RESOURCES)},
                "code": {"type": "string"},
                "codes": {"type": "array", "items": {"type": "string"}},
                "start": {"type": "string"},
                "end": {"type": "string"},
                "limit": {"type": "integer"},
                "adjust": {"type": "string", "description": "日线复权 n/f/b/fr/br"},
                "question": {"type": "string"},
            },
            "required": ["resource"],
        },
    ),
    market_fetch,
)
