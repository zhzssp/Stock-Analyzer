from __future__ import annotations

from datetime import datetime


def _parse(day: str | None) -> datetime | None:
    if not day:
        return None
    text = str(day)[:10]
    try:
        return datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        return None


def compute_bottom(bars: list[dict], price: float | None) -> dict:
    lows = []
    highs = []
    dates = []
    for row in bars or []:
        lo, hi = row.get("l"), row.get("h")
        day = _parse(row.get("d"))
        if lo is None or hi is None or day is None:
            continue
        lows.append((day, float(lo)))
        highs.append((day, float(hi)))
        dates.append(day)
    if not lows:
        return {
            "low1y": None,
            "low_long": None,
            "high": None,
            "off_low": None,
            "multiple": None,
            "target": None,
            "span_years": None,
            "note": "无日线，不能算底/顶",
        }
    last = max(dates)
    year = [v for d, v in lows if (last - d).days <= 365]
    low1y = min(year) if year else min(v for _, v in lows)
    low_long = min(v for _, v in lows)
    high = max(v for _, v in highs)
    span = (last - min(dates)).days / 365.25
    target = round(low_long * 1.5, 2)
    off = None
    if price not in (None, "") and low_long:
        off = round((float(price) - low_long) / low_long * 100, 2)
    multiple = round(high / low_long, 2) if low_long else None
    note = f"日线覆盖约 {span:.1f} 年"
    if span < 17:
        note += "，长窗底不是 17 年完整窗口"
    return {
        "low1y": low1y,
        "low_long": low_long,
        "high": high,
        "off_low": off,
        "multiple": multiple,
        "target": target,
        "span_years": round(span, 1),
        "note": note,
    }
