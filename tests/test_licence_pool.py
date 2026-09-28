import json
from datetime import date

from src.market.licence_pool import LicencePool, is_licence_unusable, is_quota_error, parse_licences


def test_parse_licences_dedupes_and_orders():
    raw = parse_licences("AAA", "BBB,CCC", "AAA,DDD")
    assert raw == ["AAA", "BBB", "CCC", "DDD"]


def test_quota_error_detection():
    assert is_quota_error(429, "")
    assert is_quota_error(200, "101:Licence证书当日次数已超出")
    assert not is_quota_error(404, "not found")


def test_quota_error_covers_mairui_wording_variants():
    """麦蕊额度提示没有统一格式：这些写法都要能识别，否则会卡在同一张已用尽的证上。"""
    assert is_quota_error(200, "101:今日调用已超限")            # 有 101，无 licence 字样
    assert is_quota_error(200, "101:额度已用尽")
    assert is_quota_error(200, "您的licence额度已用尽")          # 无 101，靠 licence + 额度
    assert is_quota_error(200, "证书当日次数已超")
    assert is_quota_error(200, "超出当日配额")
    # 这些不能误判成额度问题
    assert not is_quota_error(404, "404:资源不存在，请检查参数是否正确！")
    assert not is_quota_error(200, '{"dm":"000001","mc":"平安银行"}')


def test_licence_unusable_is_not_quota():
    """证书无效 ≠ 额度用尽：前者次日不会恢复，不能记进 exhausted。"""
    assert is_licence_unusable(401, "")
    assert is_licence_unusable(403, "")
    assert is_licence_unusable(200, "licence 无效")
    assert is_licence_unusable(200, "证书已过期")
    assert not is_licence_unusable(200, '{"dm":"000001"}')
    assert not is_licence_unusable(404, "404:资源不存在")
    # 额度提示不算「证书不可用」
    assert not is_licence_unusable(200, "101:Licence证书当日次数已超出")


def test_client_rotates_to_next_licence_on_quota_error(monkeypatch, tmp_path):
    """额度用尽时 _get 要自动换下一张，并把用尽的那张记进 exhausted（不打真实接口）。"""
    from src.market import client as client_mod
    from src.market.client import MarketClient
    from src.market.licence_registry import LicenceRegistry

    class Resp:
        def __init__(self, text):
            self.status_code = 200
            self.text = text

        def json(self):
            return {"ok": 1}

        def raise_for_status(self):
            return None

    calls = []

    def fake_get(url, timeout=None):
        calls.append(url)
        if len(calls) == 1:
            return Resp("101:Licence证书当日次数已超出")
        return Resp('{"ok":1}')

    monkeypatch.setattr(client_mod.httpx, "get", fake_get)

    reg = LicenceRegistry(state_path=tmp_path / "reg.json", sync_env=False)
    reg.add("renewable", "KEY-A")
    reg.add("renewable", "KEY-B")

    client = MarketClient.__new__(MarketClient)
    client.offline = False
    client.sample_only = False
    client._registry = reg
    client.licence = reg.active()
    client._unusable = set()
    client.licence_switches = 0
    client.query_refresh_mode = "full"
    client.slow_cache_stats = {}

    assert client._get("/anything") == {"ok": 1}
    assert len(calls) == 2
    assert "KEY-B" in calls[1]
    assert reg.renewable_available() == ["KEY-B"]   # KEY-A 已记用尽
    assert client.licence == "KEY-B"
    assert client.licence_switches == 1


def test_pool_rotates_on_exhausted(tmp_path):
    state = tmp_path / "licence_pool.json"
    pool = LicencePool(["KEY-A", "KEY-B"], state_path=state)
    assert pool.active() == "KEY-A"
    assert pool.mark_exhausted("KEY-A") == "KEY-B"
    assert pool.active() == "KEY-B"
    assert pool.mark_exhausted("KEY-B") == ""
    assert pool.exhausted_today()

    saved = json.loads(state.read_text(encoding="utf-8"))
    assert saved["date"] == date.today().isoformat()
    assert saved["exhausted"] == ["KEY-A", "KEY-B"]


def test_pool_resets_next_day(tmp_path):
    state = tmp_path / "licence_pool.json"
    state.write_text(
        json.dumps({"date": "2020-01-01", "exhausted": ["KEY-A"], "queue": ["KEY-B"]}),
        encoding="utf-8",
    )
    pool = LicencePool(["KEY-A", "KEY-B"], state_path=state)
    assert pool.active() == "KEY-A"


def test_pool_repair_recovers_corrupt_empty_queue(tmp_path):
    state = tmp_path / "licence_pool.json"
    state.write_text(
        json.dumps(
            {
                "date": date.today().isoformat(),
                "exhausted": ["KEY-B"],
                "queue": [],
            }
        ),
        encoding="utf-8",
    )
    pool = LicencePool(["KEY-A", "KEY-B"], state_path=state)
    assert pool.active() == "KEY-A"
    assert pool.repair() is True
    assert pool.active() == "KEY-A"
