from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.config import settings
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
# 取数任务的调度顺序。bars 最重（一次 500 根日线 + 底顶 + x 日收盘），排在最前面投出去，
# 否则最长的任务拖在队尾，整轮的尾延迟就是它决定的。
SLOW_FETCH_ORDER = ("bars", "profile", "holders", "finance", "flow", "indicators")


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
        on_quotes: Any = None,
        on_row: Any = None,
    ) -> list[dict]:
        """on_quotes / on_row 用于流式查询：先送一批只有行情的行，再逐只送完整行。

        两者都在 worker 线程里被调用（取数已并发），调用方要自己做线程安全。
        """
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
                on_quotes=on_quotes,
                on_row=on_row,
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
        on_quotes: Any = None,
        on_row: Any = None,
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

        if on_quotes is not None:
            # 现价是批量取的（1~3 次请求），这里就已经有全部行的行情；
            # 先把只有行情的行送出去，界面立刻有东西可看，慢字段随后逐只补。
            FAST_KEYS = ("name", "code", "price", "pct", "pe", "pb")
            fast_specs = [s for s in specs if s.key in FAST_KEYS]
            if fast_specs:
                fast_rows = []
                for inst in instruments:
                    q = quotes.get(inst.code6) or {}
                    row = {
                        "code6": inst.code6,
                        "code_full": inst.code_full,
                        "name": inst.name,
                        "market": inst.market,
                        "as_of": q.get("as_of") or clock_meta.get("as_of") or "",
                        "quote_source": q.get("source") or clock_meta.get("source") or "",
                    }
                    for spec in fast_specs:
                        row[spec.key] = self._value(
                            spec.key,
                            inst,
                            {
                                "quote": q,
                                "profile": {},
                                "holders": {},
                                "finance": {},
                                "flow": {},
                                "bottom": {},
                                "indicators": {},
                                "card": derive_card_metrics(q.get("p"), (cards or {}).get(inst.code6), None),
                            },
                        )
                    fast_rows.append(row)
                try:
                    on_quotes(fast_rows)
                except Exception:
                    pass

        def new_bag(inst: Instrument) -> dict[str, Any]:
            return {
                "quote": quotes.get(inst.code6) or {},
                "profile": {},
                "holders": {},
                "finance": {},
                "flow": {},
                "bottom": {},
                "indicators": {},
                "x_price": None,
            }

        def fetch_slow(kind: str, inst: Instrument) -> Any:
            """一个字段块 = 一次可并发的取数任务。"""
            if kind == "profile":
                return self.market.profile(inst, extra=concept_extra)
            if kind == "holders":
                return self.market.holders(inst)
            if kind == "finance":
                return self.market.finance(inst)
            if kind == "flow":
                series = self.market.capital_flow(inst)
                return series[-1] if series else {}
            if kind == "indicators":
                return self.market.indicators(inst)
            # bars：日线最重（一次 500 根），底顶和 x 日收盘都基于它，合成一个任务。
            bars = self.market.history(inst)
            return {
                "bottom": compute_bottom(bars, (quotes.get(inst.code6) or {}).get("p")),
                "x_price": self.market.close_on_date(inst, x_date) if (x_date and "x_price" in keys) else None,
            }

        def apply_slow(bag: dict, kind: str, value: Any) -> None:
            if kind == "bars":
                bag["bottom"] = (value or {}).get("bottom") or {}
                bag["x_price"] = (value or {}).get("x_price")
            elif isinstance(value, dict):
                bag[kind] = value

        def assemble(inst: Instrument, bag: dict) -> dict:
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
            if on_row is not None:
                try:
                    on_row(row)
                except Exception:
                    pass
            return row

        def build_row(inst: Instrument) -> dict:
            """旧路径：一只票内部串行取完再组装（QUERY_TASK_POOL=0 时走这条）。"""
            bag = new_bag(inst)
            for kind in SLOW_FETCH_ORDER:
                if kind in need:
                    apply_slow(bag, kind, fetch_slow(kind, inst))
            return assemble(inst, bag)

        # 并发数刻意保守（默认 4），配合服务端的限频；可在 .env 用 QUERY_WORKERS 调。
        # 关键是「在飞请求数」恒等于 workers：任务池只改变调度粒度，不改变并发度。
        workers = max(1, int(getattr(settings, "query_workers", 0) or 4))
        kinds = [k for k in SLOW_FETCH_ORDER if k in need]
        use_task_pool = bool(getattr(settings, "query_task_pool", True))

        if use_task_pool and kinds and instruments:
            bags = {inst.code6: new_bag(inst) for inst in instruments}
            abort = threading.Event()
            errors: list[BaseException] = []

            def run_task(kind: str, inst: Instrument) -> None:
                if abort.is_set():
                    return
                try:
                    value = fetch_slow(kind, inst)
                except BaseException as exc:  # noqa: BLE001 - 收集起来，最后统一抛
                    errors.append(exc)
                    # 额度耗尽 / 派不出证：剩下的任务再跑也是同一个结果，别白等一轮。
                    abort.set()
                    return
                apply_slow(bags[inst.code6], kind, value)

            # 按 kind 外层铺开：同一种接口一起打，最重的 bars 排在前面先投出去，
            # 否则最长的那个任务会拖在队尾，尾延迟就是它决定的。
            tasks = [(kind, inst) for kind in kinds for inst in instruments]
            with ThreadPoolExecutor(max_workers=min(workers, len(tasks))) as pool:
                list(pool.map(lambda item: run_task(*item), tasks))
            if errors:
                raise errors[0]
            # 组装必须串行且按 instruments 原序：导出、分页切片、快照都依赖这个顺序。
            rows = [assemble(inst, bags[inst.code6]) for inst in instruments]
        elif workers > 1 and len(instruments) > 1:
            with ThreadPoolExecutor(max_workers=min(workers, len(instruments))) as pool:
                rows = list(pool.map(build_row, instruments))
        else:
            rows = [build_row(i) for i in instruments]
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
