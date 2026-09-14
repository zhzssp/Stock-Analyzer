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
    keys = {s.key for s in registry.all()}
    assert keys.issubset(rows[0].keys())


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
