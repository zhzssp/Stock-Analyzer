"""A 股交易日历（麦蕊 tcalendar/list/{年}）。离线用 fixtures 工作日切片。"""

from __future__ import annotations

from datetime import date, timedelta

def _norm_day(value: str | None) -> str:
    return str(value or "").replace("-", "").replace("/", "")[:8]


def trading_days_for_year(year: int, market) -> set[str]:
    if market.offline:
        from src.market.fixtures import TRADING_DAYS

        raw = TRADING_DAYS.get(str(year)) or TRADING_DAYS.get(year) or []
        return {str(x) for x in raw}
    key = f"tcalendar_{year}"
    cached = market._cache_get(key)
    if isinstance(cached, list) and cached:
        return {str(x) for x in cached}
    data = market._try_get(f"/tcalendar/list/{year}") or []
    days = [str(x) for x in data] if isinstance(data, list) else []
    if days and not market.sample_only:
        market._cache_put(key, days)
    return set(days)


def is_trading_day(day: str, market) -> bool:
    d = _norm_day(day)
    if not d:
        return False
    if market.offline:
        year_days = trading_days_for_year(int(d[:4]), market)
        if year_days:
            return d in year_days
        try:
            dt = date(int(d[:4]), int(d[4:6]), int(d[6:8]))
        except ValueError:
            return False
        return dt.weekday() < 5
    return d in trading_days_for_year(int(d[:4]), market)


def prev_trading_day(day: str, market, max_back: int = 12) -> str | None:
    d = _norm_day(day)
    if not d:
        return None
    try:
        cur = date(int(d[:4]), int(d[4:6]), int(d[6:8]))
    except ValueError:
        return None
    for _ in range(max_back):
        cur -= timedelta(days=1)
        token = cur.strftime("%Y%m%d")
        if is_trading_day(token, market):
            return token
    return None


def nearest_trading_day_on_or_before(day: str, market, max_back: int = 12) -> str | None:
    d = _norm_day(day)
    if not d:
        return None
    if is_trading_day(d, market):
        return d
    return prev_trading_day(d, market, max_back=max_back)
