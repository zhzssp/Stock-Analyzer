from __future__ import annotations

from typing import Any

from src.market.client import MarketClient
from src.market.normalize import Instrument
from src.query.bottom import compute_bottom
from src.query.cards import derive_card_metrics
from src.query.registry import registry

REFRESH_QUOTE = "quote"
REFRESH_CACHE = "cache"
REFRESH_SNAPSHOT = "snapshot"
REFRESH_FULL = "full"
SLOW_DEPS = frozenset({"profile", "holders", "finance", "flow", "bars", "indicators"})


def fetch_need(column_need: set[str], refresh_mode: str) -> set[str]:
    """P0 快刷只拉现价；P2 cache/full 按列需要拉慢字段（cache 走 TTL 分项缓存）。"""
    mode = (refresh_mode or REFRESH_FULL).strip().lower()
    if mode == REFRESH_QUOTE:
        return {d for d in column_need if d == "quote"}
    if mode == REFRESH_SNAPSHOT:
        return set()
    return set(column_need)


class QueryEngine:
    """Deterministic field assembly. New columns = new FieldSpec, not a new engine."""

    def __init__(self, market: MarketClient) -> None:
        self.market = market
        self.last_clock_meta: dict = {}
        self.last_slow_cache: dict = {}

    def fields(self) -> list[dict]:
        out: list[dict] = []
        for s in registry.all():
            item = {
                "key": s.key,
                "label": s.label,
                "group": s.group,
                "alertable": s.alertable,
                "realtime": s.realtime,
                "default": s.default,
            }
            if s.unavailable:
                item["unavailable"] = s.unavailable
            out.append(item)
        return out

    def run(
        self,
        instruments: list[Instrument],
        field_keys: list[str] | None = None,
        cards: dict[str, dict] | None = None,
        writer: str = "",
        concept_extra: dict | None = None,
        x_date: str | None = None,
        force_live: bool = False,
        refresh_mode: str = REFRESH_FULL,
    ) -> list[dict]:
        keys = field_keys or registry.default_keys()
        specs = [registry.get(k) for k in keys]
        column_need = {dep for spec in specs for dep in spec.requires}
        if any(s.group == "card" for s in specs):
            column_need.add("quote")
        if "x_price" in keys and x_date:
            column_need.add("bars")
        need = fetch_need(column_need, refresh_mode)
        mode = (refresh_mode or REFRESH_FULL).strip().lower()
        prev_mode = getattr(self.market, "query_refresh_mode", REFRESH_FULL)
        self.market.query_refresh_mode = mode
        self.market.slow_cache_stats = {"hits": 0, "misses": 0}
        try:
            return self._run_rows(
                instruments,
                keys,
                specs,
                need,
                refresh_mode,
                cards,
                writer,
                concept_extra,
                x_date,
                force_live,
            )
        finally:
            self.market.query_refresh_mode = prev_mode

    def _run_rows(
        self,
        instruments: list[Instrument],
        keys: list[str],
        specs: list,
        need: set[str],
        refresh_mode: str,
        cards: dict[str, dict] | None,
        writer: str,
        concept_extra: dict | None,
        x_date: str | None,
        force_live: bool,
    ) -> list[dict]:
        quotes: dict[str, dict] = {}
        clock_meta = {"as_of": "", "source": "", "enabled": False, "reason": ""}
        if "quote" in need:
            from src.market.clock import align_quotes

            quote_extra = [] if (refresh_mode or "").strip().lower() == REFRESH_QUOTE else None
            quotes, clock_meta = align_quotes(
                self.market,
                instruments,
                writer=writer,
                force_live=force_live,
                extra_codes=quote_extra,
            )
        self.last_clock_meta = clock_meta
        rows = []
        for inst in instruments:
            bag: dict[str, Any] = {
                "quote": quotes.get(inst.code6) or {},
                "profile": {},
                "holders": {},
                "finance": {},
                "flow": {},
                "bottom": {},
                "indicators": {},
                "x_price": None,
            }
            if "profile" in need:
                bag["profile"] = self.market.profile(inst, extra=concept_extra)
            if "holders" in need:
                bag["holders"] = self.market.holders(inst)
            if "finance" in need:
                bag["finance"] = self.market.finance(inst)
            if "flow" in need:
                series = self.market.capital_flow(inst)
                latest = series[-1] if series else {}
                bag["flow"] = latest
            if "indicators" in need:
                bag["indicators"] = self.market.indicators(inst)
            if "bars" in need:
                bars = self.market.history(inst)
                bag["bottom"] = compute_bottom(bars, (bag["quote"] or {}).get("p"))
                if x_date and "x_price" in keys:
                    bag["x_price"] = self.market.close_on_date(inst, x_date)
            row = {
                "code6": inst.code6,
                "code_full": inst.code_full,
                "name": inst.name,
                "market": inst.market,
                "as_of": (quotes.get(inst.code6) or {}).get("as_of") or clock_meta.get("as_of") or "",
                "quote_source": (quotes.get(inst.code6) or {}).get("source") or clock_meta.get("source") or "",
            }
            derived = derive_card_metrics(
                (bag["quote"] or {}).get("p"),
                (cards or {}).get(inst.code6),
                (bag["bottom"] or {}).get("target"),
            )
            bag["card"] = derived
            for spec in specs:
                row[spec.key] = self._value(spec.key, inst, bag)
            rows.append(row)
        self.last_slow_cache = dict(getattr(self.market, "slow_cache_stats", {}) or {})
        return rows

    def _value(self, key: str, inst: Instrument, bag: dict) -> Any:
        q, p, h, f, fl, b = bag["quote"], bag["profile"], bag["holders"], bag["finance"], bag["flow"], bag["bottom"]
        ind = bag.get("indicators") or {}
        mapping = {
            "name": inst.name,
            "code": inst.code_full,
            "price": q.get("p"),
            "pct": q.get("pc"),
            "pe": q.get("pe"),
            "pb": q.get("sjl"),
            "turnover": q.get("hs"),
            "mcap": q.get("sz"),
            "fcap": q.get("lt"),
            "pct3": ind.get("pct3"),
            "pct5": ind.get("pct5"),
            "pct10": ind.get("pct10"),
            "pct60": q.get("zdf60"),
            "pct_ytd": q.get("zdfnc"),
            "x_price": bag.get("x_price"),
            "industry": p.get("industry"),
            "sector": p.get("sector"),
            "sw_l1": p.get("sw_l1"),
            "hot_concepts": p.get("hot_concepts"),
            "concept": p.get("concept"),
            "business": p.get("business"),
            "holders": h.get("holders"),
            "top_holders": h.get("top_holders"),
            "flow_in": fl.get("inflow"),
            "flow_out": fl.get("outflow"),
            "flow_net": fl.get("net_in"),
            "northbound": None,
            "zgb": f.get("zgb"),
            "ltgb": f.get("ysltag"),
            "mgwfplr": f.get("mgwfplr"),
            "yffy": f.get("yffy"),
            "mgjzc": f.get("mgjzc"),
            "eps": f.get("jbmgsy"),
            "gross": f.get("xsmlv"),
            "net": f.get("jlv"),
            "low1y": b.get("low1y"),
            "low_long": b.get("low_long"),
            "high": b.get("high"),
            "off_low": b.get("off_low"),
            "multiple": b.get("multiple"),
            "target": b.get("target"),
            "low_note": b.get("note"),
            "buy_low": bag.get("card", {}).get("buy_low"),
            "buy_high": bag.get("card", {}).get("buy_high"),
            "reduce_at": bag.get("card", {}).get("reduce_at"),
            "cost": bag.get("card", {}).get("cost"),
            "vs_cost": bag.get("card", {}).get("vs_cost"),
            "dist_buy": bag.get("card", {}).get("dist_buy"),
            "dist_reduce": bag.get("card", {}).get("dist_reduce"),
            "thesis": bag.get("card", {}).get("thesis") or "",
            "reduce_for_rule": bag.get("card", {}).get("reduce_for_rule"),
        }
        return mapping.get(key)
