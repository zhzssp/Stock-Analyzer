"""现网冒烟：证书池 + 关键麦蕊接口。"""
from __future__ import annotations

import json
import sys
from datetime import date

from src.config import settings
from src.market.client import MarketClient
from src.market.normalize import normalize_instrument

PASS: list[tuple[str, str]] = []
FAIL: list[tuple[str, str]] = []


def ok(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append((name, detail))
    sym = "PASS" if cond else "FAIL"
    line = f"[{sym}] {name}"
    if detail:
        line += f"  {detail}"
    print(line)


def main() -> int:
    print("=" * 60)
    print("现网冒烟", date.today().isoformat())
    print("=" * 60)
    print("证书链:", [k[:8] + "..." for k in settings.licence_chain])
    print()

    m = MarketClient()
    h = m.health()
    ok("MarketClient 初始化", h["status"] == "live", f"status={h['status']}, sample_only={h['sample_only']}")

    pool = h.get("licence_pool") or {}
    active = pool.get("active") or h.get("licence_active") or ""
    ok("证书池活跃证书", active.startswith("2FE37018"), f"active={active[:8]}...")
    ok("证书池可用数", len(pool.get("available") or []) >= 1, f"available={len(pool.get('available') or [])}/{pool.get('total')}")
    exhausted = pool.get("exhausted_today") or []
    if exhausted:
        print(f"  注: 今日已用尽备用证书 {len(exhausted)} 张: {[x[:8] + '...' for x in exhausted]}")

    codes = ["000001", "600038", "002230"]
    prices: dict[str, float | None] = {}
    for c in codes:
        suffix = ".SH" if c.startswith("6") else ".SZ"
        inst = normalize_instrument(f"{c}{suffix}")
        q = m.quote(inst)
        prices[c] = q.get("p")
        print(f"  行情 {c}: p={q.get('p')} source={q.get('source')}")
    distinct = len({p for p in prices.values() if p is not None})
    ok("数据源真实性(三码不同价)", distinct >= 2, f"distinct_prices={distinct}")

    lst = m.list_hs()
    ok("hslt/list 全市场", len(lst) > 1000, f"count={len(lst)}")

    try:
        up = m.limit_pool_codes("up")
        ok("涨停池 ztgc", True, f"codes={len(up)}")
    except Exception as e:
        ok("涨停池 ztgc", False, str(e))

    try:
        tree = m.hszg_tree()
        ok("概念树 hszg/list", isinstance(tree, list) and len(tree) > 0, f"nodes={len(tree)}")
    except Exception as e:
        ok("概念树 hszg/list", False, str(e))

    inst = normalize_instrument("600038.SH")
    try:
        ind = m.indicators(inst)
        ok("短线指标 indicators", any(k in ind for k in ("pct3", "pct5", "pct10")), f"keys={list(ind.keys())[:6]}")
    except Exception as e:
        ok("短线指标 indicators", False, str(e))

    try:
        x = m.close_on_date(inst, "20250918")
        ok("X日价 close_on_date", x is not None and x > 0, f"close={x}")
    except Exception as e:
        ok("X日价 close_on_date", False, str(e))

    try:
        from src.market.calendar import trading_days_for_year

        days = trading_days_for_year(2025, m)
        ok("交易日历 tcalendar", len(days) > 200, f"days={len(days)}")
    except Exception as e:
        ok("交易日历 tcalendar", False, str(e))

    try:
        ann = m.announcements(inst, limit=2)
        ok("公司公告 announcements", isinstance(ann, list), f"rows={len(ann)}")
    except Exception as e:
        ok("公司公告 announcements", False, str(e))

    try:
        dtc = m.dragon_tiger_codes()
        ok("龙虎榜 dragon_tiger", isinstance(dtc, set), f"codes={len(dtc)}")
    except Exception as e:
        ok("龙虎榜 dragon_tiger", False, str(e))

    try:
        top = m.sector_funds_top("industry", limit=3)
        ok("板块资金 sector_funds", isinstance(top, list) and len(top) > 0, f"rows={len(top)}")
    except Exception as e:
        ok("板块资金 sector_funds", False, str(e))

    try:
        bj = m.list_bj()
        ok("北交所列表 bj/list", len(bj) > 0, f"count={len(bj)}")
    except Exception as e:
        ok("北交所列表 bj/list", False, str(e))

    print()
    print("证书池状态:", json.dumps(pool, ensure_ascii=False))
    print()
    print("=" * 60)
    print(f"结果: {len(PASS)} PASS / {len(FAIL)} FAIL")
    if FAIL:
        print("失败项:")
        for n, d in FAIL:
            print(f"  - {n}: {d}")
        return 1
    print("现网冒烟通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
