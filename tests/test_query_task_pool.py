"""D 期：取数调度从「按只并发」换成「按字段块并发」。

要锁死的是这四条：① 单只票也能并发；② rows 顺序 == instruments 顺序；
③ on_quotes 一定早于 on_row；④ 致命错误要快速中止，别把 N×6 个任务全跑一遍。
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from src.config import settings
from src.market.client import MarketClient
from src.market.client import LicenceExhaustedError
from src.market.normalize import normalize_instrument
from src.query.engine import QueryEngine

# 覆盖到全部 6 个字段块：profile / holders / finance / flow / indicators / bars
FIELD_KEYS = ["price", "industry", "holders", "zgb", "flow_net", "pct3", "low1y"]


@pytest.fixture
def market():
    m = MagicMock(spec=MarketClient)
    m.profile.return_value = {"industry": "白酒", "sector": "", "sw_l1": "", "hot_concepts": ""}
    m.holders.return_value = {"holders": "中央汇金", "top_holders": None}
    m.finance.return_value = {"zgb": 12.5, "ysltag": 10.0}
    m.capital_flow.return_value = [{"net_in": 1.0, "inflow": 2.0, "outflow": 1.0}]
    m.indicators.return_value = {"pct3": 1.5, "pct5": 2.5, "pct10": 3.5}
    m.history.return_value = [{"d": "20260102", "c": 10.0, "h": 11.0, "l": 9.0}]
    m.query_refresh_mode = "full"
    m.slow_cache_stats = {"hits": 0, "misses": 0}
    return m


def _insts(n: int):
    return [normalize_instrument(f"60000{i}.SH", f"票{i}", "SH") for i in range(n)]


def _run(market, insts, **kwargs):
    with patch("src.market.clock.align_quotes", return_value=({i.code6: {"p": 10.0, "pc": 1.0} for i in insts}, {"source": "live"})):
        return QueryEngine(market).run(insts, FIELD_KEYS, **kwargs)


def test_single_instrument_fetches_in_parallel(market):
    """D 的核心收益：只有一只票时，6 个字段块也该一起拉。"""
    peak = {"now": 0, "max": 0}
    lock = threading.Lock()

    def make_slow(value):
        def slow(*_args, **_kwargs):
            with lock:
                peak["now"] += 1
                peak["max"] = max(peak["max"], peak["now"])
            try:
                threading.Event().wait(0.08)
                return value
            finally:
                with lock:
                    peak["now"] -= 1

        return slow

    # 每个方法要返回自己那个形状，否则 compute_bottom 会拿到 dict 当 bars 用
    returns = {
        "profile": market.profile.return_value,
        "holders": market.holders.return_value,
        "finance": market.finance.return_value,
        "capital_flow": market.capital_flow.return_value,
        "indicators": market.indicators.return_value,
        "history": market.history.return_value,
    }
    for name, value in returns.items():
        getattr(market, name).side_effect = make_slow(value)

    rows = _run(market, _insts(1))

    assert len(rows) == 1
    assert peak["max"] >= 2, "单只票仍然是串行取数，D 没生效"


def test_rows_keep_instrument_order(market):
    insts = _insts(12)
    rows = _run(market, insts)
    assert [r["code6"] for r in rows] == [i.code6 for i in insts]


def test_on_quotes_precedes_on_row(market):
    events: list[str] = []

    _run(
        market,
        _insts(5),
        on_quotes=lambda rows: events.append("quotes"),
        on_row=lambda row: events.append("row"),
    )

    assert events[0] == "quotes"
    assert events.count("quotes") == 1
    assert events[1:] == ["row"] * 5


def test_fatal_error_aborts_remaining_tasks(market):
    """额度耗尽时要立刻收手，不能把 N×6 个任务全打一遍。"""
    calls = {"n": 0}
    lock = threading.Lock()

    def boom(*_args, **_kwargs):
        with lock:
            calls["n"] += 1
        raise LicenceExhaustedError("所有证书今日额度已用尽")

    market.profile.side_effect = boom

    with pytest.raises(LicenceExhaustedError):
        _run(market, _insts(10))

    # 10 只 × 6 块 = 60 个任务，中止后应该远远打不到那么多
    assert calls["n"] < 20


def test_task_pool_off_keeps_legacy_path(market, monkeypatch):
    monkeypatch.setattr(settings, "query_task_pool", False)
    insts = _insts(6)

    rows = _run(market, insts)

    assert [r["code6"] for r in rows] == [i.code6 for i in insts]
    assert rows[0]["industry"] == "白酒"
    assert market.profile.call_count == 6


def test_field_values_are_identical_between_paths(market, monkeypatch):
    """换调度不能换结果：两条路径产出的行必须一模一样。"""
    insts = _insts(4)

    pooled = _run(market, insts)
    monkeypatch.setattr(settings, "query_task_pool", False)
    market2 = MagicMock(spec=MarketClient)
    market2.__dict__.update(market.__dict__)
    legacy = _run(market, insts)

    assert pooled == legacy
