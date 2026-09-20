from __future__ import annotations

from typing import Any

from src.market.client import MarketClient
from src.market.normalize import Instrument
from src.query.bottom import compute_bottom
from src.query.cards import derive_card_metrics
from src.query.registry import registry


class QueryEngine:
    """Deterministic field assembly. New columns = new FieldSpec, not a new engine."""

    def __init__(self, market: MarketClient) -> None:
        self.market = market

    def fields(self) -> list[dict]:
        return [
            {
                "key": s.key,
                "label": s.label,
                "group": s.group,
                "alertable": s.alertable,
                "realtime": s.realtime,
                "default": s.default,
            }
            for s in registry.all()
        ]

    def run(
        self,
        instruments: list[Instrument],
        field_keys: list[str] | None = None,
        cards: dict[str, dict] | None = None,
        writer: str = "",
    ) -> list[dict]:
        keys = field_keys or registry.default_keys()
        specs = [registry.get(k) for k in keys]
        need = {dep for spec in specs for dep in spec.requires}
        if any(s.group == "card" for s in specs):
            need.add("quote")
        quotes: dict[str, dict] = {}
        clock_meta = {"as_of": "", "source": "", "enabled": False}
        if "quote" in need:
            from src.market.clock import align_quotes

            quotes, clock_meta = align_quotes(self.market, instruments, writer=writer)
        rows = []
        for inst in instruments:
            bag: dict[str, Any] = {
                "quote": quotes.get(inst.code6) or {},
                "profile": {},
                "holders": {},
                "finance": {},
                "flow": {},
                "bottom": {},
            }
            if "profile" in need:
                bag["profile"] = self.market.profile(inst)
            if "holders" in need:
                bag["holders"] = self.market.holders(inst)
            if "finance" in need:
                bag["finance"] = self.market.finance(inst)
            if "flow" in need:
                series = self.market.capital_flow(inst)
                latest = series[-1] if series else {}
                bag["flow"] = latest
            if "bars" in need:
                bars = self.market.history(inst)
                bag["bottom"] = compute_bottom(bars, (bag["quote"] or {}).get("p"))
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
        return rows

    def _value(self, key: str, inst: Instrument, bag: dict) -> Any:
        q, p, h, f, fl, b = bag["quote"], bag["profile"], bag["holders"], bag["finance"], bag["flow"], bag["bottom"]
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
            "pct60": q.get("zdf60"),
            "pct_ytd": q.get("zdfnc"),
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
