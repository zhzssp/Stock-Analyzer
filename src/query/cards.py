from __future__ import annotations

from typing import Any


def _num(value: Any) -> float | None:
    if value in (None, "", "-", "—"):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None


def card_dict(item) -> dict:
    return {
        "thesis": getattr(item, "thesis", "") or "",
        "cost": _num(getattr(item, "cost", None)),
        "shares": _num(getattr(item, "shares", None)),
        "buy_low": _num(getattr(item, "buy_low", None)),
        "buy_high": _num(getattr(item, "buy_high", None)),
        "reduce_price": _num(getattr(item, "reduce_price", None)),
        "invalid_if": getattr(item, "invalid_if", "") or "",
        "group": getattr(item, "group_name", "") or "自选",
    }


def derive_card_metrics(price: Any, card: dict | None, target: Any = None) -> dict:
    card = card or {}
    px = _num(price)
    buy_low = _num(card.get("buy_low"))
    buy_high = _num(card.get("buy_high"))
    reduce_at = _num(card.get("reduce_price"))
    cost = _num(card.get("cost"))
    reduce_for_dist = reduce_at if reduce_at is not None else _num(target)
    vs_cost = round((px - cost) / cost * 100, 2) if px is not None and cost else None
    dist_buy = None
    if px is not None and buy_high is not None:
        dist_buy = round((px - buy_high) / buy_high * 100, 2)
    elif px is not None and buy_low is not None:
        dist_buy = round((px - buy_low) / buy_low * 100, 2)
    dist_reduce = None
    if px is not None and reduce_for_dist is not None:
        dist_reduce = round((reduce_for_dist - px) / reduce_for_dist * 100, 2)
    return {
        "buy_low": buy_low,
        "buy_high": buy_high,
        "reduce_at": reduce_at,
        "cost": cost,
        "vs_cost": vs_cost,
        "dist_buy": dist_buy,
        "dist_reduce": dist_reduce,
        "thesis": card.get("thesis") or "",
        "reduce_for_rule": reduce_for_dist,
    }
