from __future__ import annotations

from typing import Any

from src.market.client import MarketClient
from src.market.normalize import Instrument
from src.query.bottom import compute_bottom
from src.query.registry import registry


class QueryEngine:
    """Deterministic field assembly. New columns = new FieldSpec, not a new engine."""

    def __init__(self, market: MarketClient) -> None:
        self.market = market

    def fields(self) -> list[dict]:
        return [
            {"key": s.key, "label": s.label, "group": s.group}
            for s in registry.all()
        ]

    def run(self, instruments: list[Instrument], field_keys: list[str] | None = None) -> list[dict]:
        keys = field_keys or registry.default_keys()
        specs = [registry.get(k) for k in keys]
        need = {dep for spec in specs for dep in spec.requires}
        quotes = self.market.quotes_many(instruments) if "quote" in need else {}
        rows = []
        for inst in instruments:
            bag: dict[str, Any] = {
                "quote": quotes.get(inst.code6) or {},
                "profile": {},
                "holders": {},
                "finance": {},
                "bottom": {},
            }
            if "profile" in need:
                bag["profile"] = self.market.profile(inst)
            if "holders" in need:
                bag["holders"] = self.market.holders(inst)
            if "finance" in need:
                bag["finance"] = self.market.finance(inst)
            if "bars" in need:
                bars = self.market.history(inst)
                bag["bottom"] = compute_bottom(bars, (bag["quote"] or {}).get("p"))
            row = {
                "code6": inst.code6,
                "code_full": inst.code_full,
                "name": inst.name,
                "market": inst.market,
            }
            for spec in specs:
                row[spec.key] = self._value(spec.key, inst, bag)
            rows.append(row)
        return rows

    def _value(self, key: str, inst: Instrument, bag: dict) -> Any:
        q, p, h, f, b = bag["quote"], bag["profile"], bag["holders"], bag["finance"], bag["bottom"]
        mapping = {
            "name": inst.name,
            "code": inst.code_full,
            "price": q.get("p"),
            "pct": q.get("pc"),
            "pe": q.get("pe"),
            "pb": q.get("sjl"),
            "industry": p.get("industry"),
            "concept": p.get("concept"),
            "business": p.get("business"),
            "holders": h.get("holders"),
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
        }
        return mapping.get(key)
