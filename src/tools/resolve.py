from __future__ import annotations

from src.market.client import MarketClient
from src.market.normalize import Instrument, code6_of, normalize_instrument
from src.models import WatchItem


def catalog(market: MarketClient, extras: list[Instrument] | None = None) -> list[Instrument]:
    seen: dict[str, Instrument] = {}
    for inst in list(market.list_hs()) + list(market.list_bj()) + list(extras or []):
        seen[inst.code6] = inst
    return list(seen.values())


def watch_instruments(ctx) -> list[Instrument]:
    items = ctx.db.query(WatchItem).filter_by(user_id=ctx.user_id).all()
    out = []
    for item in items:
        out.append(
            normalize_instrument(item.code_full or item.code6, item.name, item.code_full.split(".")[-1] if "." in item.code_full else "")
        )
    return out


def mentioned(text: str, market: MarketClient, extras: list[Instrument] | None = None) -> list[Instrument]:
    pool = catalog(market, extras)
    hits: list[Instrument] = []
    for inst in pool:
        if inst.code6 and inst.code6 in text:
            hits.append(inst)
        elif inst.code_full and inst.code_full in text:
            hits.append(inst)
        elif inst.name and inst.name in text:
            hits.append(inst)
    if hits:
        return _unique(hits)
    for inst in pool:
        if inst.name and len(inst.name) >= 2 and inst.name[:2] in text:
            hits.append(inst)
    return _unique(hits)


def resolve_codes(raw_codes: list[str] | None, market: MarketClient, extras: list[Instrument] | None = None) -> list[Instrument]:
    if not raw_codes:
        return []
    known = {i.code6: i for i in catalog(market, extras)}
    out = []
    for raw in raw_codes:
        key = code6_of(str(raw))
        out.append(known[key] if key in known else normalize_instrument(str(raw)))
    return _unique(out)


def _unique(items: list[Instrument]) -> list[Instrument]:
    seen = set()
    out = []
    for inst in items:
        if inst.code6 in seen:
            continue
        seen.add(inst.code6)
        out.append(inst)
    return out
