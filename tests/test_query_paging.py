"""方案 C 的后端一半：/query/run 的分页与后端排序。

前端只拿一页时，排序必须后端做 —— 否则排的只是已加载的那一段。
"""

from fastapi.testclient import TestClient

from src.main import app


def _login(client):
    login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_query_run_without_limit_keeps_legacy_shape():
    """不传 limit 时行为不变：rows 就是全部，并带上 total / has_more=False。"""
    with TestClient(app) as client:
        headers = _login(client)
        body = client.post("/api/query/run", json={}, headers=headers).json()
        assert body["rows"]
        assert body["total"] == len(body["rows"])
        assert body["has_more"] is False
        assert body["offset"] == 0


def test_query_run_paging_returns_total_and_has_more():
    with TestClient(app) as client:
        headers = _login(client)
        full = client.post("/api/query/run", json={}, headers=headers).json()
        total = full["total"]
        assert total >= 2

        first = client.post("/api/query/run", json={"limit": 1}, headers=headers).json()
        assert len(first["rows"]) == 1
        assert first["total"] == total          # total 是整池行数，不是本页
        assert first["offset"] == 0
        assert first["has_more"] is True

        second = client.post("/api/query/run", json={"limit": 1, "offset": 1}, headers=headers).json()
        assert second["offset"] == 1
        # 两页拼起来要和整池一一对应，不能错位也不能重复
        assert first["rows"][0]["code6"] != second["rows"][0]["code6"]
        assert [r["code6"] for r in first["rows"] + second["rows"]] == [r["code6"] for r in full["rows"][:2]]


def test_query_run_sort_is_applied_before_paging():
    """先排序再切片：第 0 页必须是全局最小/最大，而不是「已加载这段里的最小」。"""
    with TestClient(app) as client:
        headers = _login(client)
        full = client.post("/api/query/run", json={}, headers=headers).json()
        rows = full["rows"]
        if not any(r.get("price") is not None for r in rows):
            return  # 离线样例没有现价时跳过

        desc = client.post(
            "/api/query/run", json={"sort_key": "price", "sort_dir": "desc", "limit": 1}, headers=headers
        ).json()
        asc = client.post(
            "/api/query/run", json={"sort_key": "price", "sort_dir": "asc", "limit": 1}, headers=headers
        ).json()

        prices = [r["price"] for r in rows if r.get("price") is not None]
        assert desc["rows"][0]["price"] == max(prices)
        assert asc["rows"][0]["price"] == min(prices)


def test_query_sort_puts_empty_values_last():
    """空值永远排最后，升序降序都一样，不能让空格子占据首页。"""
    with TestClient(app) as client:
        headers = _login(client)
        rows = client.post("/api/query/run", json={}, headers=headers).json()["rows"]
        mixed = [r for r in rows if r.get("price") is not None]
        empty = [r for r in rows if r.get("price") is None]
        if not (mixed and empty):
            return

        for direction in ("asc", "desc"):
            body = client.post(
                "/api/query/run", json={"sort_key": "price", "sort_dir": direction}, headers=headers
            ).json()
            got = body["rows"]
            assert all(r.get("price") is not None for r in got[: len(mixed)])
            assert all(r.get("price") is None for r in got[len(mixed) :])


def test_query_stream_paging_reports_full_total():
    """流式也分页：只流一页，但 meta.total 要报整池行数，前端才知道还要不要再拉。"""
    with TestClient(app) as client:
        headers = _login(client)
        full = client.post("/api/query/run", json={}, headers=headers).json()
        resp = client.post("/api/query/stream", json={"limit": 1}, headers=headers)
        assert resp.status_code == 200, resp.text
        text = resp.text
        assert "event: meta" in text
        for raw in text.split("event: "):
            if not raw.startswith("meta"):
                continue
            payload = raw.split("data:", 1)[1].split("\n\n", 1)[0]
            import json as _json

            meta = _json.loads(payload)
            assert meta["total"] == full["total"]  # 整池行数，不是本页


def test_paging_does_not_truncate_table_snapshot():
    """分页只影响返回给前端的那一段，表级快照必须还是整表。"""
    with TestClient(app) as client:
        headers = _login(client)
        full = client.post("/api/query/run", json={"refresh_mode": "full"}, headers=headers).json()
        # 只取一页，快照仍应是整表
        client.post("/api/query/run", json={"refresh_mode": "full", "limit": 1}, headers=headers)
        snap = client.post("/api/query/run", json={"refresh_mode": "snapshot"}, headers=headers)
        assert snap.status_code == 200, snap.text
        assert snap.json()["total"] == full["total"]
