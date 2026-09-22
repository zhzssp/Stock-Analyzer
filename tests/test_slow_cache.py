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


def test_read_fresh_expires(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    write("slow_test_1", {"x": 1})
    import time

    with patch("src.market.slow_cache.time.time", return_value=time.time() + 10_000):
        assert read_fresh("slow_test_1", ttl_sec=60) is None
