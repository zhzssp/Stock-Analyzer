import json

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


def test_single_code_query_does_not_replace_pool_snapshot():
    """详情和「只看这一只」走临时代码，不能把自选快照换成这一只。"""
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
        kept = full.json()["total"]
        one = WATCH_SEED[0].code_full
        detail = client.post(
            "/api/query/run",
            json={"codes": [one], "refresh_mode": "cache", "pool_name": "筛选一次"},
            headers=headers,
        )
        assert detail.status_code == 200
        snap = client.post("/api/query/run", json={"refresh_mode": "snapshot"}, headers=headers)
        assert snap.status_code == 200, snap.text
        body = snap.json()
        assert body["total"] == kept
        assert body["snapshot"]["pool_id"] == "watch"


def test_stream_covering_the_pool_saves_and_a_short_page_does_not():
    """自选不满一页时，流式查询仍是整表，要留下快照；只流一只不能把快照切短。"""
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        client.put(
            "/api/watchlist",
            json={"items": [{"code": i.code_full} for i in WATCH_SEED[:2]]},
            headers=headers,
        )
        streamed = client.post(
            "/api/query/stream",
            json={"refresh_mode": "cache", "limit": 100},
            headers=headers,
        )
        assert streamed.status_code == 200, streamed.text
        snap = client.post("/api/query/run", json={"refresh_mode": "snapshot"}, headers=headers)
        assert snap.status_code == 200, snap.text
        assert snap.json()["total"] == 2
        client.post("/api/query/stream", json={"refresh_mode": "cache", "limit": 1}, headers=headers)
        again = client.post("/api/query/run", json={"refresh_mode": "snapshot"}, headers=headers)
        assert again.status_code == 200, again.text
        assert again.json()["total"] == 2


def test_legacy_one_stock_file_is_not_a_watch_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    folder = tmp_path / "snapshots"
    folder.mkdir()
    (folder / "user_1.json").write_text(
        json.dumps(
            {
                "pool": "筛选一次",
                "rows": [{"code6": "920091", "name": "大鹏工业", "price": 33.51, "industry": "机械"}],
                "field_keys": ["price", "industry"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    assert load_table_snapshot(1, "watch") is None


def test_legacy_watch_file_still_loads(tmp_path, monkeypatch):
    monkeypatch.setattr("src.config.settings.data_dir", tmp_path)
    folder = tmp_path / "snapshots"
    folder.mkdir()
    (folder / "user_1.json").write_text(
        json.dumps({"pool": "自选", "rows": [{"code6": "600038", "price": 10}], "field_keys": ["price"]}),
        encoding="utf-8",
    )
    snap = load_table_snapshot(1, "watch")
    assert snap and snap["rows"][0]["price"] == 10
