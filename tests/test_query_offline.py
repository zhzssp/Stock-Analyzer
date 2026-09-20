from src.market.client import MarketClient, resolve_instruments
from src.query.engine import QueryEngine
from src.query.registry import registry


def test_offline_query_has_figure1_fields():
    market = MarketClient()
    assert market.offline is True
    engine = QueryEngine(market)
    insts = resolve_instruments(["600038.SH", "000725.SZ"], market)
    rows = engine.run(insts)
    assert len(rows) == 2
    assert rows[0]["name"] == "中直股份"
    assert rows[0]["price"] == 26.86
    assert {s.key for s in registry.all() if s.default}.issubset(rows[0].keys())
    assert "buy_low" not in rows[0]
    assert rows[0]["low1y"] == 24.6
    assert rows[0]["low_long"] == 24.6
    assert rows[0]["high"] == 36.9
    assert rows[0]["target"] == 36.9
    assert rows[0]["off_low"] == 9.19
    assert rows[0]["pb"] == 1.25
    assert "turnover" not in rows[0]
    extra = engine.run(insts, field_keys=["name", "turnover", "mcap", "fcap", "pct60", "pct_ytd"])
    assert extra[0]["turnover"] == 0.86
    assert extra[0]["mcap"] == 412.5
    assert extra[0]["fcap"] == 318.2
    assert extra[0]["pct60"] == 8.4
    assert extra[0]["pct_ytd"] == 12.1
    assert extra[0]["code6"] == "600038"
    assert extra[1]["code6"] == "000725"
    extra_keys = {s.key for s in registry.all() if s.key in {"turnover", "mcap", "fcap", "pct60", "pct_ytd"}}
    assert extra_keys
    assert not any(registry.get(k).default for k in extra_keys)


def test_code_normalizer_keeps_suffix():
    insts = resolve_instruments(["600038"], MarketClient())
    assert insts[0].code_full.endswith(".SH")


def test_search_splits_hs_kc_bj():
    market = MarketClient()
    bj = market.search(market="bj")
    assert {x["code6"] for x in bj} >= {"430017", "830799"}
    assert all(x["market"] == "bj" for x in bj)
    jun = market.search(q="军工", market="hs")
    assert {x["code6"] for x in jun} >= {"600038", "000768"}
    assert all(x["market"] == "hs" for x in jun)


def test_bj_query_allows_empty_finance():
    market = MarketClient()
    engine = QueryEngine(market)
    rows = engine.run(resolve_instruments(["430017"], market))
    assert rows[0]["name"] == "星昊医药"
    assert rows[0]["price"] == 8.46
    assert rows[0]["yffy"] is None
    assert rows[0]["holders"] is None
