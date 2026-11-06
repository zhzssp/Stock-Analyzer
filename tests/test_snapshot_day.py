"""按上海日期另存查询表，以及日期框打开时的选择和淘汰。"""

import json

from fastapi.testclient import TestClient

from src.main import app
from src.query.snapshot import (
    _iter_snapshots,
    load_day_for_view,
    load_table_snapshot,
    merge_partial_snapshot,
    save_table_snapshot,
)


def _use(tmp_path, monkeypatch, keep=30):
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    monkeypatch.setattr("src.config.settings.snapshot_day_keep", keep)
    seq = {"n": 0}

    def stamp():
        seq["n"] += 1
        return f"2026-11-01T00:00:00.{seq['n']:06d}+00:00"

    monkeypatch.setattr("src.query.snapshot._stamp", stamp)


def _row(price, code6="600000"):
    return {"code6": code6, "code_full": f"{code6}.SH", "name": "样例", "price": price}


def _save(user, stamp, *, pool="自选", pool_id="watch", price=1, mode="full", code6="600000"):
    save_table_snapshot(
        user,
        pool=pool,
        pool_id=pool_id,
        field_keys=["name", "price"],
        codes=[f"{code6}.SH"],
        rows=[_row(price, code6)],
        clock={},
        refresh_mode=mode,
        saved_at=stamp,
    )


def _safe(pool_id: str) -> str:
    text = (pool_id or "watch").strip() or "watch"
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in text) or "watch"


def _day(root, user, day, pool_id):
    return root / "snapshots" / "days" / f"user_{user}" / day / f"{_safe(pool_id)}.json"


def _live(root, user, pool_id):
    return root / "snapshots" / f"user_{user}_{_safe(pool_id)}.json"


def _entries(root, user):
    path = root / "snapshots" / "days" / f"user_{user}" / "index.json"
    return json.loads(path.read_text(encoding="utf-8"))["entries"]


def test_two_days_keep_both_files(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    _save(1, "2026-10-28T10:00:00+00:00", price=1)
    _save(1, "2026-10-29T10:00:00+00:00", price=2)
    assert json.loads(_day(tmp_path, 1, "2026-10-28", "watch").read_text(encoding="utf-8"))["rows"][0]["price"] == 1
    assert json.loads(_day(tmp_path, 1, "2026-10-29", "watch").read_text(encoding="utf-8"))["rows"][0]["price"] == 2
    assert len(_entries(tmp_path, 1)) == 2
    assert len(_iter_snapshots(1)) == 1
    assert load_table_snapshot(1)["rows"][0]["price"] == 2
    assert load_day_for_view(1, "2026-10-28")["rows"][0]["price"] == 1
    assert load_table_snapshot(1)["rows"][0]["price"] == 2


def test_same_day_overwrites_only_that_day(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    _save(1, "2026-10-28T10:00:00+00:00", price=1)
    _save(1, "2026-10-29T02:00:00+00:00", price=2)
    _save(1, "2026-10-29T06:00:00+00:00", price=3)
    assert _day(tmp_path, 1, "2026-10-28", "watch").exists()
    day = json.loads(_day(tmp_path, 1, "2026-10-29", "watch").read_text(encoding="utf-8"))
    assert day["rows"][0]["price"] == 3
    assert len(_entries(tmp_path, 1)) == 2
    assert {item["date"] for item in _entries(tmp_path, 1)} == {"2026-10-28", "2026-10-29"}


def test_shanghai_day_crosses_utc_midnight(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    _save(1, "2026-10-29T16:30:00+00:00", price=8)
    assert _day(tmp_path, 1, "2026-10-30", "watch").exists()
    assert not _day(tmp_path, 1, "2026-10-29", "watch").exists()
    assert load_day_for_view(1, "2026-10-30")["rows"][0]["price"] == 8
    assert load_day_for_view(1, "2026-10-29") is None


def test_latest_complete_table_wins(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    _save(1, "2026-10-29T01:00:00+00:00", pool="科创板全部", pool_id="board:kc", price=1, code6="688001")
    _save(1, "2026-10-29T05:00:00+00:00", pool="沪市全部", pool_id="exchange:sh", price=2, code6="600000")
    opened = load_day_for_view(1, "2026-10-29")
    assert opened["pool_id"] == "exchange:sh"
    assert opened["pool"] == "沪市全部"
    assert opened["complete"] is True


def test_later_partial_does_not_beat_an_earlier_complete_table(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    _save(1, "2026-10-29T01:00:00+00:00", pool="科创板全部", pool_id="board:kc", price=1, code6="688001")
    merge_partial_snapshot(
        1,
        pool="沪市全部",
        pool_id="exchange:sh",
        field_keys=["name", "price"],
        rows=[_row(5)],
        clock={},
        refresh_mode="full",
        total=936,
        saved_at="2026-10-29T06:00:00+00:00",
    )
    opened = load_day_for_view(1, "2026-10-29")
    assert opened["pool_id"] == "board:kc"
    assert opened["complete"] is True


def test_only_partial_opens_with_covered_count(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    merge_partial_snapshot(
        1,
        pool="沪市全部",
        pool_id="exchange:sh",
        field_keys=["name", "price"],
        rows=[_row(5)],
        clock={},
        refresh_mode="full",
        total=936,
        saved_at="2026-10-29T06:00:00+00:00",
    )
    opened = load_day_for_view(1, "2026-10-29")
    assert opened["pool"] == "沪市全部"
    assert opened["complete"] is False
    assert opened["covered"] == 1
    assert opened["total"] == 936


def test_quote_refresh_updates_the_copy_and_that_day(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    # 整表替换仍不接受「只刷行情」，避免空的行业财务盖掉副本。
    _save(1, "2026-10-29T02:00:00+00:00", mode="quote", price=9)
    assert load_table_snapshot(1) is None
    merge_partial_snapshot(
        1,
        pool="自选",
        pool_id="watch",
        field_keys=["name", "price"],
        rows=[_row(9)],
        clock={},
        refresh_mode="quote",
        total=1,
        saved_at="2026-10-29T03:00:00+00:00",
    )
    snap = load_table_snapshot(1)
    assert snap["rows"][0]["price"] == 9
    opened = load_day_for_view(1, "2026-10-29")
    assert opened["rows"][0]["price"] == 9


def test_keep_drops_the_oldest_last_used(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch, keep=2)
    _save(1, "2026-10-01T01:00:00+00:00", price=1)
    _save(1, "2026-10-02T01:00:00+00:00", price=2)
    _save(1, "2026-10-03T01:00:00+00:00", price=3)
    assert not _day(tmp_path, 1, "2026-10-01", "watch").exists()
    assert _day(tmp_path, 1, "2026-10-02", "watch").exists()
    assert _day(tmp_path, 1, "2026-10-03", "watch").exists()
    assert {item["date"] for item in _entries(tmp_path, 1)} == {"2026-10-02", "2026-10-03"}


def test_opening_a_day_makes_it_the_last_to_evict(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch, keep=2)
    _save(1, "2026-10-01T01:00:00+00:00", price=1)
    _save(1, "2026-10-02T01:00:00+00:00", price=2)
    assert load_day_for_view(1, "2026-10-01")["rows"][0]["price"] == 1
    _save(1, "2026-10-03T01:00:00+00:00", price=3)
    assert _day(tmp_path, 1, "2026-10-01", "watch").exists()
    assert not _day(tmp_path, 1, "2026-10-02", "watch").exists()
    assert _day(tmp_path, 1, "2026-10-03", "watch").exists()


def test_rewriting_the_same_day_does_not_evict_another(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch, keep=2)
    _save(1, "2026-10-01T01:00:00+00:00", price=1)
    _save(1, "2026-10-02T01:00:00+00:00", price=2)
    _save(1, "2026-10-01T08:00:00+00:00", price=9)
    assert _day(tmp_path, 1, "2026-10-01", "watch").exists()
    assert _day(tmp_path, 1, "2026-10-02", "watch").exists()
    assert len(_entries(tmp_path, 1)) == 2


def test_live_file_survives_eviction_and_opening_does_not_overwrite_it(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch, keep=1)
    _save(1, "2026-10-01T01:00:00+00:00", pool="沪市全部", pool_id="exchange:sh", price=1)
    _save(1, "2026-10-02T01:00:00+00:00", pool="深市全部", pool_id="exchange:sz", price=2, code6="000001")
    assert not _day(tmp_path, 1, "2026-10-01", "exchange:sh").exists()
    assert _live(tmp_path, 1, "exchange:sh").exists()
    assert json.loads(_live(tmp_path, 1, "exchange:sh").read_text(encoding="utf-8"))["rows"][0]["price"] == 1
    assert json.loads(_live(tmp_path, 1, "exchange:sz").read_text(encoding="utf-8"))["rows"][0]["price"] == 2
    assert load_day_for_view(1, "2026-10-01") is None
    assert json.loads(_live(tmp_path, 1, "exchange:sz").read_text(encoding="utf-8"))["rows"][0]["price"] == 2


def test_api_snapshot_day(tmp_path, monkeypatch):
    _use(tmp_path, monkeypatch)
    from src.db import SessionLocal
    from src.models import User

    with TestClient(app) as client:
        db = SessionLocal()
        try:
            user = db.query(User).filter_by(username="hanish").first()
            uid = user.id
        finally:
            db.close()
        _save(uid, "2026-10-29T05:00:00+00:00", pool="沪市全部", pool_id="exchange:sh", price=12)
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        found = client.get("/api/query/snapshot-day", params={"date": "2026-10-29"}, headers=headers)
        empty = client.get("/api/query/snapshot-day", params={"date": "1999-01-01"}, headers=headers)
    assert found.status_code == 200
    body = found.json()
    assert body["found"] is True
    assert body["pool"] == "沪市全部"
    assert body["pool_id"] == "exchange:sh"
    assert body["rows"][0]["price"] == 12
    assert body["fields"]
    assert empty.status_code == 200
    assert empty.json()["found"] is False
    assert empty.json()["message"] == "这一天没有可打开的查询表"


def test_export_picks_the_latest_three_days_for_this_pool(tmp_path, monkeypatch):
    """最近三天可以不连续。更早的一天和别的池子都不能混进这次导出。"""
    _use(tmp_path, monkeypatch)
    from io import BytesIO

    from openpyxl import load_workbook

    from src.db import SessionLocal
    from src.models import User

    with TestClient(app) as client:
        db = SessionLocal()
        try:
            uid = db.query(User).filter_by(username="hanish").first().id
        finally:
            db.close()
        _save(uid, "2026-10-26T02:00:00+00:00", price=1)
        _save(uid, "2026-10-28T02:00:00+00:00", price=2)
        merge_partial_snapshot(
            uid,
            pool="自选",
            pool_id="watch",
            field_keys=["name", "price"],
            rows=[_row(3)],
            clock={},
            refresh_mode="quote",
            total=10,
            saved_at="2026-10-30T02:00:00+00:00",
        )
        _save(uid, "2026-11-01T02:00:00+00:00", price=4)
        _save(uid, "2026-11-02T02:00:00+00:00", pool="沪市全部", pool_id="exchange:sh", price=9, code6="600000")
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        listed = client.get("/api/query/snapshot-days", params={"pool": "watch"}, headers=headers)
        assert listed.status_code == 200, listed.text
        days = listed.json()["days"]
        assert [item["date"] for item in days] == ["2026-11-01", "2026-10-30", "2026-10-28"]
        assert days[1]["complete"] is False
        assert days[1]["covered"] == 1
        assert days[1]["total"] == 10
        rejected = client.post(
            "/api/query/export",
            json={"pool": "watch", "fields": ["name", "price"], "snapshot_dates": ["2026-10-26"]},
            headers=headers,
        )
        assert rejected.status_code == 400
        other = client.post(
            "/api/query/export",
            json={"pool": "watch", "fields": ["name", "price"], "snapshot_dates": ["2026-11-02"]},
            headers=headers,
        )
        assert other.status_code == 400
        exported = client.post(
            "/api/query/export",
            json={
                "pool": "watch",
                "pool_name": "自选",
                "fields": ["name", "price"],
                "snapshot_dates": ["2026-10-28", "2026-11-01"],
                "export_label": "自选_当前栏目_2026-11-01_2026-10-28",
            },
            headers=headers,
        )
        assert exported.status_code == 200, exported.text
        assert exported.json()["days"] == ["2026-11-01", "2026-10-28"]
        downloaded = client.get(exported.json()["download_url"], headers=headers)
        wb = load_workbook(BytesIO(downloaded.content), data_only=True)
        assert wb.sheetnames[:2] == ["2026-11-01", "2026-10-28"]
        assert wb["2026-11-01"].cell(2, 2).value == 4
        assert wb["2026-10-28"].cell(2, 2).value == 2
        assert "meta" in wb.sheetnames
