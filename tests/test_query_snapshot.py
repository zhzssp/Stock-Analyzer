from fastapi.testclient import TestClient

from src.main import app
from src.market.fixtures import WATCH_SEED
from src.query.engine import REFRESH_SNAPSHOT, fetch_need
from src.query.snapshot import load_table_snapshot, rows_from_snapshot, save_table_snapshot


def test_fetch_need_snapshot_empty():
    assert fetch_need({"quote", "finance"}, REFRESH_SNAPSHOT) == set()


def test_snapshot_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    rows = [{"code6": "600038", "code_full": "600038.SH", "name": "中直", "price": 10, "pct": 1}]
    save_table_snapshot(
        1,
        pool="watch",
        field_keys=["code", "price", "pct"],
        codes=["600038.SH"],
        rows=rows,
        clock={"as_of": "2026-09-22", "source": "live"},
        refresh_mode="full",
    )
    snap = load_table_snapshot(1)
    assert snap and snap["rows"][0]["price"] == 10


def test_api_snapshot_mode():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        client.put(
            "/api/watchlist",
            json={"items": [{"code": i.code_full} for i in WATCH_SEED[:2]]},
            headers=headers,
        )
        full = client.post("/api/query/run", json={"refresh_mode": "full"}, headers=headers)
        assert full.status_code == 200
        snap = client.post("/api/query/run", json={"refresh_mode": "snapshot"}, headers=headers)
        assert snap.status_code == 200
        assert snap.json()["refresh_mode"] == "snapshot"
        assert snap.json()["rows"]
