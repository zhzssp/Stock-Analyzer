from unittest.mock import patch

from src.config import settings
from src.market.normalize import normalize_instrument
from src.market.slow_cache import read_fresh, write
from src.query.engine import REFRESH_CACHE, fetch_need


def test_fetch_need_cache_includes_slow_deps():
    need = {"quote", "profile", "finance", "bars"}
    assert fetch_need(need, REFRESH_CACHE) == need


def test_profile_cache_hit_skips_http(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    inst = normalize_instrument("600519.SH", "贵州茅台", "SH")
    payload = {"industry": "白酒", "concept": "消费", "business": "酒", "source": "live"}
    write("slow_profile_600519", payload)

    from src.market.client import MarketClient

    client = MarketClient.__new__(MarketClient)
    client.offline = False
    client.sample_only = False
    client.query_refresh_mode = "cache"
    client.slow_cache_stats = {"hits": 0, "misses": 0}

    with patch.object(client, "_get") as get:
        out = client.profile(inst)
        get.assert_not_called()
    assert out["industry"] == "白酒"


def test_finance_cache_key_is_not_shadowed(monkeypatch, tmp_path):
    """回归：finance 里曾经用 `for key in (...)` 覆盖了外层的缓存键 key，
    财务缓存被写进 jlv.json，于是每次查询都重新拉一遍财务（每只 3 次请求白烧）。
    """
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    inst = normalize_instrument("600519.SH", "贵州茅台", "SH")

    from src.market.client import MarketClient

    client = MarketClient.__new__(MarketClient)
    client.offline = False
    client.sample_only = False
    client.query_refresh_mode = "full"
    client.slow_cache_stats = {"hits": 0, "misses": 0}

    with patch.object(
        client,
        "_get",
        side_effect=[[{"mgwfplr": 1.0}], [{"yffy": 2}], [{"zgb": 3, "ysltag": 4}]],
    ):
        out = client.finance(inst)

    assert out["zgb"] == 3
    assert (settings.cache_dir / "slow_finance_600519.json").exists()
    assert not (settings.cache_dir / "jlv.json").exists()


def test_finance_uses_latest_period_not_the_first_row(monkeypatch, tmp_path):
    """每股指标和股本的列表从旧到新，第 1 条是上市初期。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    inst = normalize_instrument("000001.SZ", "平安银行", "SZ")
    psi = [
        {"jzrq": "2007-03-31", "mgwfplr": 0.72, "mgjzc": 3.65, "jbmgsy": 0.27, "xsmlv": "-", "jlv": 22.7},
        {"jzrq": "2026-06-30", "mgwfplr": 14.8, "mgjzc": 24.13, "jbmgsy": 1.24, "xsmlv": "-", "jlv": 30.1},
    ]
    income = [{"jzrq": "2007-03-31", "yffy": 1}, {"jzrq": "2026-06-30", "yffy": 9}]
    cap = [
        {"bdrq": "19910403", "zgb": 48500171, "ysltag": 26500000},
        {"bdrq": "20260630", "zgb": 19405918198, "ysltag": 19405684991},
    ]

    from src.market.client import MarketClient

    client = MarketClient.__new__(MarketClient)
    client.offline = False
    client.sample_only = False
    client.query_refresh_mode = "full"
    client.slow_cache_stats = {"hits": 0, "misses": 0}

    with patch.object(client, "_get", side_effect=[psi, income, cap]):
        out = client.finance(inst)

    assert out["mgjzc"] == 24.13
    assert out["jbmgsy"] == 1.24
    assert out["mgwfplr"] == 14.8
    assert out["jlv"] == 30.1
    assert out["yffy"] == 9
    assert out["zgb"] == 19405918198
    assert out["ysltag"] == 19405684991


def test_holder_rows_use_latest_period():
    from src.market.client import _holder_rows

    flat = [
        {"jzrq": "2003-12-31", "gdmc": "博时裕富证券投资基金", "cgpm": 1, "cgsl": 1, "cgbl": 0.4},
        {"jzrq": "2003-12-31", "gdmc": "深圳国债服务中心", "cgpm": 2, "cgsl": 1, "cgbl": 0.2},
        {"jzrq": "2026-06-30", "gdmc": "香港中央结算有限公司", "cgpm": 2, "cgsl": 10, "cgbl": 3.8},
        {"jzrq": "2026-06-30", "gdmc": "中国平安保险(集团)股份有限公司", "cgpm": 1, "cgsl": 20, "cgbl": 49.5},
    ]
    names = [row["gdmc"] for row in _holder_rows(flat)]
    assert names == ["中国平安保险(集团)股份有限公司", "香港中央结算有限公司"]

    grouped = [
        {"jzrq": "1992-12-31", "sdgd": [{"pm": 1, "gdmc": "深圳市投资管理公司"}]},
        {"jzrq": "2026-06-30", "sdgd": [{"pm": 1, "gdmc": "中国平安保险(集团)股份有限公司"}]},
    ]
    assert _holder_rows(grouped)[0]["gdmc"] == "中国平安保险(集团)股份有限公司"


def test_read_fresh_expires(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    write("slow_test_1", {"x": 1})
    import time

    with patch("src.market.slow_cache.time.time", return_value=time.time() + 10_000):
        assert read_fresh("slow_test_1", ttl_sec=60) is None
