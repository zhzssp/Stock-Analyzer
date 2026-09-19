from src.agents.rules import eval_near_bottom, eval_near_target
from src.market.client import MarketClient, resolve_instruments
from src.market.fixtures import CARD_SEED, EXPORT_SHARE, EVENTS, FINANCE, HOLDERS, QUOTE, WATCH_SEED
from src.query.cards import derive_card_metrics
from src.query.engine import QueryEngine


def test_offline_universe_covers_boards_and_sectors():
    market = MarketClient()
    hs = {i.code6 for i in market.list_hs()}
    bj = {i.code6 for i in market.list_bj()}
    assert hs >= {i.code6 for i in WATCH_SEED}
    assert {"000858", "601318", "688981", "300760", "002594", "000063"} <= hs
    assert {"430017", "830799", "833533"} <= bj
    cy = {i.code6 for i in market.list_board("cy")}
    kc = {i.code6 for i in market.list_board("kc")}
    assert cy >= {"300750", "300274", "300760"}
    assert kc >= {"688001", "688981"}
    banks = market.search(q="大金融", market="hs")
    assert {x["code6"] for x in banks} >= {"000001", "601166", "601318"}
    liquor = market.search(q="白酒")
    assert {x["code6"] for x in liquor} >= {"600519", "000858"}
    chip = market.search(q="半导体国产替代")
    assert {x["code6"] for x in chip} >= {"688001", "688981"}


def test_quote_scenarios_limits_pb_and_sparse_bj():
    assert QUOTE["300274"]["pc"] == 20.0
    assert QUOTE["002415"]["pc"] == -10.0
    assert QUOTE["688981"]["pc"] == 19.85
    assert QUOTE["000858"]["pc"] == 9.97
    for code, row in QUOTE.items():
        if code == "430017":
            assert row["pe"] is None
            assert row["sjl"] is None
            continue
        assert row.get("sjl") is not None
    assert "430017" not in FINANCE
    assert "430017" not in HOLDERS
    assert FINANCE["830799"]["yffy"] == 1.2
    assert "挪威政府全球养老基金" in HOLDERS["600038"]["holders"]
    assert any(x["Gdmc"] == "中央汇金" for x in HOLDERS["601166"]["holders_detail"])


def test_bottom_and_card_alert_paths():
    market = MarketClient()
    engine = QueryEngine(market)
    rows = {r["code6"]: r for r in engine.run(resolve_instruments(["600038", "601012", "430017"], market))}
    assert rows["600038"]["off_low"] == 9.19
    assert rows["600038"]["pb"] == 1.25
    assert rows["601012"]["off_low"] <= 8
    assert rows["430017"]["yffy"] is None
    assert rows["430017"]["holders"] is None
    ok, _ = eval_near_bottom(rows["601012"], {"off_low_max": 8})
    assert ok is True
    ok, _ = eval_near_bottom(rows["600038"], {"off_low_max": 8})
    assert ok is False
    derived = derive_card_metrics(rows["600038"]["price"], CARD_SEED["600038"], rows["600038"]["target"])
    hit, _ = eval_near_target({"price": rows["600038"]["price"], "reduce_at": derived["reduce_at"], "target": rows["600038"]["target"]}, {})
    assert hit is True


def test_events_unlock_and_export_share_fixture():
    assert EVENTS["601899"]["unlock"]
    assert EVENTS["000725"]["seo"]
    assert EVENTS["600038"]["dividends"]
    assert "600038" not in EXPORT_SHARE
    assert EXPORT_SHARE["300750"]["export_pct"] == "41"
    from src.tools.base import ToolContext
    from src.tools import registry

    ctx = ToolContext(user_id=1, db=None, market=MarketClient(), engine=QueryEngine(MarketClient()))
    empty = registry.run("export_share", {"code": "600038.SH"}, ctx)
    assert empty.ok
    assert empty.data[0]["export_pct"] is None
    filled = registry.run("export_share", {"code": "300750.SZ"}, ctx)
    assert filled.ok
    assert filled.data[0]["export_pct"] == "41"
