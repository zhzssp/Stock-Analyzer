from __future__ import annotations

import csv
from pathlib import Path

from src.config import settings
from src.market.futures_map import catalog as futures_catalog
from src.market.futures_map import contracts_for
from src.market.institutions import match_many
from src.market.taxonomy import catalog as taxonomy_catalog
from src.market.taxonomy import classify
from src.tools.base import ToolContext, ToolResult, ToolSpec
from src.tools.registry import registry
from src.tools.resolve import mentioned, resolve_codes, watch_instruments


def _pick(args: dict, ctx: ToolContext):
    codes = args.get("codes") or ([args["code"]] if args.get("code") else None)
    extras = watch_instruments(ctx)
    if codes:
        return resolve_codes(codes, ctx.market, extras)
    return mentioned(args.get("question") or args.get("name") or "", ctx.market, extras) or extras[:1]


def taxonomy_lookup(args: dict, ctx: ToolContext) -> ToolResult:
    q = (args.get("query") or args.get("industry") or args.get("question") or "").strip()
    if q:
        tax = classify(q, q)
        return ToolResult(ok=True, data={"query": q, **tax, "catalog": taxonomy_catalog()}, source="taxonomy_lookup", cite="分类主数据")
    insts = _pick(args, ctx)
    rows = []
    for inst in insts:
        p = ctx.market.profile(inst)
        rows.append({"name": inst.name, "code": inst.code_full, **classify(p.get("industry") or "", p.get("concept") or "")})
    return ToolResult(ok=True, data=rows or taxonomy_catalog(), source="taxonomy_lookup", cite="分类主数据")


def fund_holding(args: dict, ctx: ToolContext) -> ToolResult:
    insts = _pick(args, ctx)
    if not insts:
        return ToolResult(ok=False, error="没有可查询的标的", source="fund_holding", cite="基金持仓")
    rows = []
    for inst in insts:
        holdings = ctx.market.fund_holdings(inst)
        names = [h.get("name") or "" for h in holdings]
        catalog = None
        if ctx.db is not None and ctx.user_id:
            from src.platform.monitor_prefs import institution_catalog_for

            catalog = institution_catalog_for(ctx.db, ctx.user_id)
        hits = match_many(names, ("fund", "etf", "stabilizer", "ib", "swf"), catalog)

        rows.append(
            {
                "name": inst.name,
                "code": inst.code_full,
                "holdings": holdings,
                "watch_hits": hits,
            }
        )
    return ToolResult(ok=True, data=rows, source="fund_holding", cite="基金持仓 · jjcg")


def futures_map(args: dict, ctx: ToolContext) -> ToolResult:
    insts = _pick(args, ctx) if args.get("code") or args.get("codes") or args.get("question") else []
    if insts:
        rows = []
        for inst in insts:
            p = ctx.market.profile(inst)
            rows.append(
                {
                    "name": inst.name,
                    "code": inst.code_full,
                    "industry": p.get("industry"),
                    "contracts": contracts_for(p.get("industry") or "", p.get("concept") or ""),
                    "quotes_enabled": False,
                }
            )
        return ToolResult(ok=True, data=rows, source="futures_map", cite="期货映射 · 无行情")
    industry = args.get("industry") or args.get("query") or ""
    return ToolResult(
        ok=True,
        data={"contracts": contracts_for(industry, industry), "catalog": futures_catalog(), "quotes_enabled": False},
        source="futures_map",
        cite="期货映射 · 无行情",
    )


def export_share(args: dict, ctx: ToolContext) -> ToolResult:
    from src.market import fixtures

    path = Path(settings.data_dir) / "export_share.csv"
    table = {}
    if path.exists():
        with path.open(encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                code = (row.get("code6") or row.get("code") or "").strip().split(".")[0]
                if code:
                    table[code] = {
                        "export_pct": row.get("export_pct") or row.get("出口占比"),
                        "overseas_pct": row.get("overseas_pct") or row.get("外市场占比"),
                        "note": row.get("note") or "",
                    }
    elif getattr(ctx.market, "offline", False):
        table = {code: dict(row) for code, row in fixtures.EXPORT_SHARE.items()}
    insts = _pick(args, ctx)
    if not insts:
        return ToolResult(
            ok=True,
            data={"rows": [], "source": "manual-csv" if table else "empty", "path": str(path)},
            source="export_share",
            cite="出口占比 · 手工表",
        )
    rows = []
    for inst in insts:
        item = table.get(inst.code6) or {"export_pct": None, "overseas_pct": None, "note": "无手工表数据"}
        rows.append({"name": inst.name, "code": inst.code_full, **item})
    return ToolResult(ok=True, data=rows, source="export_share", cite="出口占比 · 手工表")


_schema = {
    "type": "object",
    "properties": {
        "code": {"type": "string"},
        "codes": {"type": "array", "items": {"type": "string"}},
        "question": {"type": "string"},
        "industry": {"type": "string"},
        "query": {"type": "string"},
    },
}

def _scan_user_sources(args: dict, ctx: ToolContext, kind: str, label: str) -> ToolResult:
    """走用户在监控「偏好」里配的白名单 URL / RSS —— 与监控侧同一条链路、同一份源。

    不是全网搜索：只抓用户自己登记过的源，命中标题/正文里出现关键词的条目。
    """
    from src.platform.monitor_prefs import sources_for
    from src.platform.web_sources import scan_sources, watch_needles

    sources = sources_for(ctx.db, ctx.user_id)
    if not sources:
        return ToolResult(
            ok=False,
            error="还没配检索源：请到监控「偏好」里添加白名单 URL / RSS",
            source="web_sources",
            cite="检索源",
        )

    name = str(args.get("name") or args.get("query") or "").strip()
    code6 = str(args.get("code") or "").strip()
    needles = watch_needles(name, code6, str(args.get("industry") or ""), str(args.get("concept") or ""))

    if needles:
        watches = [(code6 or "ALL", name or "查询", needles)]
    else:
        # 没给关键词：按自选清单来，和监控默认行为一致
        from src.tools.market_tools import watch_instruments

        watches = [
            (i.code6, i.name, watch_needles(i.name, i.code6, "", ""))
            for i in watch_instruments(ctx)
        ]
    if not watches:
        return ToolResult(ok=False, error="没有可检索的标的", source="web_sources", cite="检索源")

    hits = scan_sources(sources, kind, watches, ctx.user_id)
    rows = [
        {
            "code6": h.code6,
            "name": h.name,
            "title": h.title,
            "url": h.url,
            "snippet": h.snippet,
            "source": h.source_name,
        }
        for h in hits[:20]
    ]
    return ToolResult(
        ok=True,
        data=rows,
        source="web_sources",
        cite=f"检索源 · {label}",
    )


def web_finance_search(args: dict, ctx: ToolContext) -> ToolResult:
    """资讯检索：只查用户配的白名单源，不做全网搜索。"""
    return _scan_user_sources(args, ctx, "news", "资讯")


def policy_news(args: dict, ctx: ToolContext) -> ToolResult:
    """产业政策：同样是白名单源，只是 kind=policy。"""
    return _scan_user_sources(args, ctx, "policy", "产业政策")


registry.register(ToolSpec("taxonomy_lookup", "板块分类", "compute", "申万一级、七大板块、2026概念", _schema), taxonomy_lookup)
registry.register(ToolSpec("fund_holding", "基金持仓", "market", "基金持股，并对照汇金/点名基金/投行白名单", _schema), fund_holding)
registry.register(
    ToolSpec("futures_map", "期货映射", "compute", "按行业给出关联期货品种。无行情源，不返回价格", _schema),
    futures_map,
)
registry.register(
    ToolSpec("export_share", "出口占比", "web", "读取 data/export_share.csv 手工表；无文件则空", _schema),
    export_share,
)
# 以前这两个是空壳（_disabled_run）。现在接上监控侧同一套白名单检索：
# 用户在「偏好」里配的源就是数据源，没配源会明确报错，不编内容。
registry.register(
    ToolSpec("web_finance_search", "资讯检索", "web", "按自选/关键词检索已配白名单的资讯（不是全网搜索）", _schema),
    web_finance_search,
)
registry.register(
    ToolSpec("policy_news", "产业政策", "web", "按行业/关键词检索已配白名单的政策信息（不是全网搜索）", _schema),
    policy_news,
)
