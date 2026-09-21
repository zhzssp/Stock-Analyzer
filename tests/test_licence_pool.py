import json
from datetime import date

from src.market.licence_pool import LicencePool, is_quota_error, parse_licences


def test_parse_licences_dedupes_and_orders():
    raw = parse_licences("AAA", "BBB,CCC", "AAA,DDD")
    assert raw == ["AAA", "BBB", "CCC", "DDD"]


def test_quota_error_detection():
    assert is_quota_error(429, "")
    assert is_quota_error(200, "101:Licence证书当日次数已超出")
    assert not is_quota_error(404, "not found")


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
