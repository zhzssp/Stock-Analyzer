from src.market.client import MarketClient, resolve_instruments
from src.market.futures_map import contracts_for
from src.market.holders_diff import diff_holders, normalize_holders
from src.market.institutions import match_institution
from src.market.taxonomy import classify
from src.query.engine import QueryEngine
from src.tools import registry


def test_taxonomy_maps_remark_sectors_and_2026_concepts():
    tax = classify("国防军工", "航空装备,直升机")
    assert tax["sector"] == "高端制造与科技"
    assert tax["sw_l1"] == "国防军工"
    tax_ai = classify("计算机", "人工智能,智能语音")
    assert "人工智能" in tax_ai["hot_list"]
    tax_new = classify("电力设备", "锂电池,新能源")
    assert "新能源" in tax_new["hot_list"]


def test_search_by_sector_and_hot_concept():
    market = MarketClient()
    banks = market.search(q="大金融", market="hs")
    assert {x["code6"] for x in banks} >= {"000001", "601166"}
    assert all(x.get("sector") == "大金融" for x in banks)
    ai = market.search(q="人工智能")
    assert {x["code6"] for x in ai} >= {"002230"}


def test_query_has_taxonomy_and_flow_columns():
    engine = QueryEngine(MarketClient())
    rows = engine.run(resolve_instruments(["600038.SH"], MarketClient()), None)
    row = rows[0]
    assert row["sector"] == "高端制造与科技"
    assert row["sw_l1"] == "国防军工"
    assert row["flow_net"] is not None
    assert row["northbound"] is None
    assert "挪威政府全球养老基金" in (row["holders"] or "")


def test_holder_diff_and_swf_alias():
    old = normalize_holders([{"Gdmc": "中直股份控股股东", "Cgbl": 48.2}])
    new = normalize_holders(
        [
            {"Gdmc": "中直股份控股股东", "Cgbl": 48.2},
            {"Gdmc": "GPFG", "Cgbl": 2.1},
        ]
    )
    diff = diff_holders(old, new)
    assert diff["changed"]
    assert diff["entered"][0]["institution"] == "挪威政府全球养老基金"
    assert match_institution("中央汇金")["kind"] == "stabilizer"
    assert match_institution("高盛")["kind"] == "ib"


def test_futures_map_has_no_quotes():
    rows = contracts_for("有色金属")
    assert {r["name"] for r in rows} >= {"铜", "铝"}
    assert all(r["quote"] is None for r in rows)
    spec = registry.get("futures_quote")
    assert spec.enabled is False
    assert registry.get("futures_map").enabled is True
    assert registry.get("web_finance_search").enabled is False
    assert registry.get("policy_news").enabled is False


def test_fund_and_export_tools():
    from src.tools.base import ToolContext
    from src.query.engine import QueryEngine

    ctx = ToolContext(user_id=1, db=None, market=MarketClient(), engine=QueryEngine(MarketClient()))
    funds = registry.run("fund_holding", {"code": "600038.SH"}, ctx)
    assert funds.ok
    names = [h["name"] for h in funds.data[0]["watch_hits"]]
    assert "易方达瑞享" in names
    empty = registry.run("export_share", {"code": "600038.SH"}, ctx)
    assert empty.ok
    assert empty.data[0]["export_pct"] is None
