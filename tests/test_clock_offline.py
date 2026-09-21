from datetime import datetime
from pathlib import Path

from src.market.clock import (
    SHANGHAI,
    align_quotes,
    clock_dir_error,
    clock_series,
    in_session,
    list_slots,
    load_slot,
    merge_quotes_into_slot,
    slot_start,
    write_universe,
)
from src.market.normalize import normalize_instrument
from src.config import ROOT, settings


class FakeMarket:
    offline = False
    sample_only = False

    def __init__(self, prices: dict[str, float] | None = None):
        self.calls = 0
        self.prices = prices or {"600038": 26.86, "000001": 11.2}

    def quotes_many(self, insts):
        self.calls += 1
        return {i.code6: {"p": self.prices.get(i.code6, 1.0), "pc": 0.5, "pe": 8, "sjl": 1.2, "source": "live"} for i in insts}


def test_slot_start_floors_to_five_minutes():
    at = datetime(2026, 9, 18, 10, 8, tzinfo=SHANGHAI)
    slot = slot_start(at)
    assert slot.hour == 10
    assert slot.minute == 5


def test_rejects_software_data_dir():
    assert clock_dir_error(settings.data_dir)
    assert clock_dir_error(ROOT)


def test_conflict_copy_does_not_double_series(tmp_path: Path):
    at = datetime(2026, 9, 18, 10, 5, tzinfo=SHANGHAI)
    merge_quotes_into_slot(tmp_path, at, {"600038": {"p": 26.0, "pc": 1.0}}, writer="a")
    day = tmp_path / "quotes" / "2026-09-18"
    conflict = day / "1005 (冲突的副本).json"
    conflict.write_text(
        '{"schema":1,"as_of":"2026-09-18T10:05:00+08:00","quotes":{"600038":{"p":99.0},"000001":{"p":11.2}}}',
        encoding="utf-8",
    )
    points = clock_series(tmp_path, "600038", "2026-09-18T10:00:00+08:00", "2026-09-18T11:00:00+08:00")
    assert len(points) == 1
    assert points[0]["p"] == 26.0
    payload = load_slot(tmp_path, "2026-09-18T10:08:00+08:00")
    assert payload["quotes"]["600038"]["p"] == 26.0
    assert payload["quotes"]["000001"]["p"] == 11.2


def test_merge_does_not_overwrite_existing_price(tmp_path: Path):
    at = datetime(2026, 9, 18, 10, 5, tzinfo=SHANGHAI)
    merge_quotes_into_slot(tmp_path, at, {"600038": {"p": 26.0}}, writer="a")
    merge_quotes_into_slot(tmp_path, at, {"600038": {"p": 99.0}, "000001": {"p": 11.0}}, writer="b")
    payload = load_slot(tmp_path, "2026-09-18T10:05:00+08:00")
    assert payload["quotes"]["600038"]["p"] == 26.0
    assert payload["quotes"]["000001"]["p"] == 11.0
    assert "a" in payload["writers"] and "b" in payload["writers"]


def test_align_uses_file_without_second_fetch(tmp_path: Path):
    at = datetime(2026, 9, 18, 10, 8, tzinfo=SHANGHAI)
    inst = normalize_instrument("600038.SH", "中直股份", "SH")
    market = FakeMarket()
    first, meta1 = align_quotes(market, [inst], writer="hanish", clock_dir=tmp_path, at=at)
    assert market.calls == 1
    assert first["600038"]["p"] == 26.86
    second, meta2 = align_quotes(market, [inst], writer="alice", clock_dir=tmp_path, at=at)
    assert market.calls == 1
    assert meta2["source"] == "clock"
    assert second["600038"]["source"] == "clock"
    slots = list_slots(tmp_path, "2026-09-18")
    assert len(slots) == 1


def test_align_force_live_skips_clock_cache(tmp_path: Path):
    at = datetime(2026, 9, 18, 10, 8, tzinfo=SHANGHAI)
    inst = normalize_instrument("600038.SH", "中直股份", "SH")
    market = FakeMarket()
    align_quotes(market, [inst], writer="hanish", clock_dir=tmp_path, at=at)
    assert market.calls == 1
    market.calls = 0
    market.prices["600038"] = 27.01
    forced, meta = align_quotes(market, [inst], writer="hanish", clock_dir=tmp_path, at=at, force_live=True)
    assert market.calls == 1
    assert meta["source"] == "live"
    assert forced["600038"]["p"] == 27.01
    assert forced["600038"]["source"] == "live"


def test_universe_union_fetched_for_tape(tmp_path: Path):
    write_universe(tmp_path, "bob", ["000001"])
    at = datetime(2026, 9, 18, 10, 5, tzinfo=SHANGHAI)
    inst = normalize_instrument("600038.SH", "中直股份", "SH")
    market = FakeMarket()
    align_quotes(market, [inst], writer="hanish", clock_dir=tmp_path, at=at)
    payload = load_slot(tmp_path, "2026-09-18T10:05:00+08:00")
    assert "600038" in payload["quotes"]
    assert "000001" in payload["quotes"]


def test_in_session_weekday_morning():
    assert in_session(datetime(2026, 9, 18, 10, 8, tzinfo=SHANGHAI)) is True
    assert in_session(datetime(2026, 9, 20, 10, 8, tzinfo=SHANGHAI)) is False
