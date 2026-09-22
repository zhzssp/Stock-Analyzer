from unittest.mock import MagicMock, patch

from src.market.client import MarketClient
from src.market.normalize import normalize_instrument
from src.query.engine import REFRESH_QUOTE, fetch_need
from src.query.engine import QueryEngine
from src.query.registry import registry


def test_fetch_need_quote_only_keeps_quote():
    need = {"quote", "profile", "finance", "bars"}
    assert fetch_need(need, REFRESH_QUOTE) == {"quote"}


def test_fetch_need_full_passthrough():
    need = {"quote", "profile"}
    assert fetch_need(need, "full") == need


def test_quote_refresh_skips_slow_fetches():
    inst = normalize_instrument("600038.SH", "中直股份", "SH")
    market = MagicMock(spec=MarketClient)
    market.profile.return_value = {"industry": "军工"}
    market.holders.return_value = {"holders": 1}
    market.finance.return_value = {"zgb": 1}
    market.capital_flow.return_value = []
    market.history.return_value = []
    market.indicators.return_value = {}

    with patch("src.market.clock.align_quotes", return_value=({"600038": {"p": 10, "pc": 1}}, {"source": "live"})):
        engine = QueryEngine(market)
        keys = registry.default_keys()
        rows = engine.run([inst], keys, refresh_mode=REFRESH_QUOTE)

    market.profile.assert_not_called()
    market.holders.assert_not_called()
    market.finance.assert_not_called()
    market.capital_flow.assert_not_called()
    market.history.assert_not_called()
    assert rows[0]["price"] == 10
    assert rows[0].get("industry") in (None, "")
