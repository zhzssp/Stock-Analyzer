from __future__ import annotations

from src.tools.base import ToolContext, ToolResult, ToolSpec
from src.tools.registry import registry
from src.tools.resolve import mentioned, resolve_codes, watch_instruments


def _pick(args: dict, ctx: ToolContext):
    codes = args.get("codes") or ([args["code"]] if args.get("code") else None)
    extras = watch_instruments(ctx)
    if codes:
        return resolve_codes(codes, ctx.market, extras)
    q = args.get("question") or args.get("name") or ""
    hits = mentioned(q, ctx.market, extras)
    return hits or extras


def _blank(value):
    if value in (None, "", "-", "—"):
        return None
    return value


def quote(args: dict, ctx: ToolContext) -> ToolResult:
    insts = _pick(args, ctx)
    if not insts:
        return ToolResult(ok=False, error="没有可查询的标的", source="quote", cite="行情")
    rows = []
    for inst in insts:
        q = ctx.market.quote(inst)
        rows.append(
            {
                "name": inst.name,
                "code": inst.code_full,
                "price": _blank(q.get("p")),
                "pct": _blank(q.get("pc")),
                "pe": _blank(q.get("pe")),
                "source": q.get("source", ""),
            }
        )
    return ToolResult(ok=True, data=rows, source="quote", cite="行情 · quote")


def company_profile(args: dict, ctx: ToolContext) -> ToolResult:
    insts = _pick(args, ctx)
    if not insts:
        return ToolResult(ok=False, error="没有可查询的标的", source="company_profile", cite="公司资料")
    rows = []
    for inst in insts:
        p = ctx.market.profile(inst)
        rows.append(
            {
                "name": inst.name,
                "code": inst.code_full,
                "industry": _blank(p.get("industry")),
                "concept": _blank(p.get("concept")),
                "business": _blank(p.get("business")),
            }
        )
    return ToolResult(ok=True, data=rows, source="company_profile", cite="公司资料 · profile")


def holders_flow(args: dict, ctx: ToolContext) -> ToolResult:
    insts = _pick(args, ctx)
    if not insts:
        return ToolResult(ok=False, error="没有可查询的标的", source="holders_flow", cite="股东")
    rows = []
    for inst in insts:
        h = ctx.market.holders(inst)
        rows.append(
            {
                "name": inst.name,
                "code": inst.code_full,
                "holders": _blank(h.get("holders")),
                "holders_detail": h.get("holders_detail") or [],
            }
        )
    return ToolResult(ok=True, data=rows, source="holders_flow", cite="股东 · holders")


def finance_snapshot(args: dict, ctx: ToolContext) -> ToolResult:
    insts = _pick(args, ctx)
    if not insts:
        return ToolResult(ok=False, error="没有可查询的标的", source="finance_snapshot", cite="财务")
    rows = []
    for inst in insts:
        f = ctx.market.finance(inst)
        rows.append(
            {
                "name": inst.name,
                "code": inst.code_full,
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
    return ToolResult(ok=True, data=rows, source="finance_snapshot", cite="财务 · finance")


def universe(args: dict, ctx: ToolContext) -> ToolResult:
    items = watch_instruments(ctx)
    return ToolResult(
        ok=True,
        data=[{"name": i.name, "code": i.code_full, "market": i.market} for i in items],
        source="universe",
        cite="自选 · universe",
    )


def _code_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "6 位或带后缀代码"},
            "codes": {"type": "array", "items": {"type": "string"}},
            "question": {"type": "string", "description": "用于从问句里解析股票"},
        },
    }


registry.register(ToolSpec("quote", "行情", "market", "查询现价、涨跌幅、市盈率", _code_schema()), quote)
registry.register(ToolSpec("company_profile", "公司资料", "market", "查询行业、概念、主营业务", _code_schema()), company_profile)
registry.register(ToolSpec("holders_flow", "十大流通股东", "market", "查询前十大流通股东摘要", _code_schema()), holders_flow)
registry.register(ToolSpec("finance_snapshot", "财务快照", "market", "查询股本、每股指标、研发费用、毛利率、净利率", _code_schema()), finance_snapshot)
registry.register(ToolSpec("universe", "自选池", "market", "列出当前用户自选", {"type": "object", "properties": {}}), universe)
