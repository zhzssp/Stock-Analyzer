from pathlib import Path

from fastapi.testclient import TestClient

from src.main import app
from src.market.fixtures import WATCH_SEED


def test_login_query_export():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        assert login.status_code == 200, login.text
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        watch = client.get("/api/watchlist", headers=headers)
        assert watch.status_code == 200
        assert len(watch.json()) >= 1

        fields = client.get("/api/query/fields", headers=headers)
        assert {x["key"] for x in fields.json()} >= {"name", "price", "holders", "yffy", "net", "sector", "flow_net", "northbound"}

        tax = client.get("/api/markets/taxonomy")
        assert tax.status_code == 200
        labels = {s["label"] for s in tax.json()["taxonomy"]["sectors"]}
        assert "大金融" in labels
        assert tax.json()["northbound"] == "未接入"

        query = client.post("/api/query/run", json={}, headers=headers)
        assert query.status_code == 200
        body = query.json()
        assert body["rows"][0]["name"]
        assert body["market"]["offline"] is True
        assert "clock" in body

        exported = client.post("/api/query/export", json={"pool_name": "自选"}, headers=headers)
        assert exported.status_code == 200
        assert exported.json()["filename"].endswith(".xlsx")
        assert exported.json()["id"]
        assert exported.json()["download_url"].endswith(f"/artifacts/{exported.json()['id']}/download")

        arts = client.get("/api/artifacts", headers=headers)
        assert arts.status_code == 200
        assert arts.json()[0]["filename"] == exported.json()["filename"]

        downloaded = client.get(exported.json()["download_url"], headers=headers)
        assert downloaded.status_code == 200
        assert downloaded.content[:2] == b"PK"
        assert "attachment" in downloaded.headers.get("content-disposition", "")


def test_s3_filter_append_and_once_query():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        reset = client.put(
            "/api/watchlist",
            json={"items": [{"code": i.code_full} for i in WATCH_SEED]},
            headers=headers,
        )
        assert reset.status_code == 200
        start = len(reset.json())
        assert start == len(WATCH_SEED)

        bj = client.get("/api/markets/instruments?market=bj")
        assert bj.status_code == 200
        codes = {x["code6"] for x in bj.json()}
        assert "430017" in codes
        assert all(x["market"] == "bj" for x in bj.json())

        maotai = client.get("/api/markets/instruments?q=茅台")
        assert any(x["code6"] == "600519" for x in maotai.json())

        kc = client.get("/api/markets/instruments?market=kc")
        kc_codes = {x["code6"] for x in kc.json()}
        assert kc_codes >= {"688001", "688981"}
        assert all(x["market"] == "kc" for x in kc.json())

        added = client.post(
            "/api/watchlist/items",
            json={"items": [{"code": "430017.BJ"}, {"code": "600519"}]},
            headers=headers,
        )
        assert added.status_code == 200
        body = added.json()
        assert len(body["added"]) == 2
        assert len(body["items"]) == start + 2

        query = client.post("/api/query/run", json={}, headers=headers)
        names = {row["name"] for row in query.json()["rows"]}
        assert "星昊医药" in names
        assert "贵州茅台" in names
        bj_row = next(row for row in query.json()["rows"] if row["code6"] == "430017")
        assert bj_row["price"] == 8.46
        assert bj_row["yffy"] is None
        assert bj_row["net"] is None

        once = client.post("/api/query/run", json={"codes": ["688001"]}, headers=headers)
        assert once.status_code == 200
        assert once.json()["rows"][0]["name"] == "华兴源创"
        after_once = client.get("/api/watchlist", headers=headers)
        assert not any(x["code6"] == "688001" for x in after_once.json())

        removed = client.delete("/api/watchlist/430017", headers=headers)
        assert removed.status_code == 200
        assert not any(x["code6"] == "430017" for x in removed.json()["items"])


def test_health_cy_export_codes_artifacts_warehouse():
    from src.config import settings

    path = settings.data_dir / "export_share.csv"
    old = path.read_bytes() if path.exists() else None
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        token = login.json()["token"]
        headers = {"Authorization": f"Bearer {token}"}

        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True
        assert "llm_status" in health.json()["agent"]
        assert {c["id"] for c in health.json()["agent"]["channels"]} >= {"log", "desktop", "webhook"}
        assert "total_human" in health.json()["storage"]

        cy = client.get("/api/markets/instruments?market=cy")
        assert cy.status_code == 200
        cy_codes = {x["code6"] for x in cy.json()}
        assert cy_codes >= {"300750", "300274", "300760"}
        assert all(code.startswith("300") for code in cy_codes)

        tax = client.get("/api/markets/taxonomy")
        assert "银行" in tax.json()["taxonomy"]["sw_l1"]
        assert tax.json()["institutions"]
        assert tax.json()["futures"]["quotes_enabled"] is False

        first = client.post("/api/query/export", json={"pool": "watch"}, headers=headers)
        second = client.post("/api/query/export", json={"codes": ["300750"]}, headers=headers)
        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["pool"] == "筛选一次"

        preview = client.get(f"/api/artifacts/{second.json()['id']}/preview", headers=headers)
        assert preview.status_code == 200
        assert preview.json()["ok"] is True
        assert preview.json()["data"]["headers"]

        diffed = client.post("/api/artifacts/diff", json={}, headers=headers)
        assert diffed.status_code == 200
        assert diffed.json()["ok"] is True
        assert "change_count" in diffed.json()["data"]

        listed = client.get("/api/artifacts", headers=headers)
        assert listed.status_code == 200
        assert any(x["id"] == second.json()["id"] for x in listed.json())

        sessions = client.get("/api/agent/sessions", headers=headers)
        assert sessions.status_code == 200

        warehouse = client.get("/api/warehouse?kind=list", headers=headers)
        assert warehouse.status_code == 200
        assert warehouse.json()["ok"] is True
        assert "artifacts" in warehouse.json()["data"]

        bars = client.get("/api/warehouse?kind=bars&code=600038&limit=8", headers=headers)
        assert bars.status_code == 200
        assert bars.json()["ok"] is True
        assert bars.json()["data"][0]["code"].startswith("600038")
        assert bars.json()["data"][0]["count"] >= 1

        try:
            uploaded = client.put(
                "/api/export-share",
                files={"file": ("export_share.csv", "code6,export_pct,overseas_pct,note\n600038,12,8,test\n", "text/csv")},
                headers=headers,
            )
            assert uploaded.status_code == 200
            share = client.get("/api/export-share?code=600038", headers=headers)
            assert share.status_code == 200
            rows = share.json()["data"]
            assert rows[0]["export_pct"] == "12"
        finally:
            if old is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(old)


def test_board_indices_offline():
    with TestClient(app) as client:
        data = client.get("/api/markets/board")
        assert data.status_code == 200
        items = data.json()["items"]
        assert [x["short"] for x in items] == ["上证", "深成", "科创"]
        by = {x["short"]: x for x in items}
        assert by["上证"]["code"] == "000001.SH"
        assert by["上证"]["p"] == 3900.87
        assert by["上证"]["pc"] == 1.86
        assert by["深成"]["code"] == "399001.SZ"
        assert by["深成"]["p"] == 13650.68
        assert by["深成"]["pc"] == 2.01
        assert by["科创"]["code"] == "000688.SH"
        assert by["科创"]["label"] == "科创50"
        assert by["科创"]["p"] == 1948.21
        assert by["科创"]["pc"] == 2.37


def test_index_quote_parser_accepts_mairui_shapes():
    from src.market.client import MarketClient, _parse_index_quote

    assert _parse_index_quote({"p": 3900.87, "pc": 1.86}) == {"p": 3900.87, "pc": 1.86}
    parsed = _parse_index_quote([{"zs": "13650.68", "zf": "+2.01%"}])
    assert parsed == {"p": 13650.68, "pc": 2.01}
    parsed = _parse_index_quote({"close": 1948.21, "zdf": 2.37})
    assert parsed == {"p": 1948.21, "pc": 2.37}

    client = MarketClient.__new__(MarketClient)
    client.offline = False
    client.sample_only = False

    def fake_try_get(path: str):
        if "000001" in path:
            return [{"p": 3900.87, "pc": 1.86}]
        if "399001" in path:
            return {"zs": 13650.68, "zf": "+2.01%"}
        if "000688" in path:
            return {"close": 1948.21, "percent": 2.37}
        return None

    client._try_get = fake_try_get
    items = {x["short"]: x for x in client.index_quotes()}
    assert items["上证"]["source"] == "live"
    assert items["上证"]["p"] == 3900.87
    assert items["深成"]["pc"] == 2.01
    assert items["科创"]["p"] == 1948.21


def test_storage_usage_endpoint():
    with TestClient(app) as client:
        denied = client.get("/api/storage")
        assert denied.status_code == 401
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        data = client.get("/api/storage", headers=headers)
        assert data.status_code == 200, data.text
        body = data.json()
        assert "data_dir" in body
        assert Path(body["data_dir"]).name == "data"
        assert "cache_bytes" in body
        assert body["limits"]["artifact_keep"] >= 1
        assert body["limits"]["bars_max"] >= 1
        assert body["limits"]["cache_max_bytes"] >= 1
        assert "clock" in body


def test_clock_dir_rejects_data_folder_and_lists_slots(tmp_path):
    from src.config import settings
    from src.market.clock import pointer_path

    pointer = pointer_path()
    backup = pointer.read_text(encoding="utf-8") if pointer.exists() else None
    try:
        with TestClient(app) as client:
            login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
            headers = {"Authorization": f"Bearer {login.json()['token']}"}
            denied = client.post("/api/clock/dir", json={"path": str(settings.data_dir)}, headers=headers)
            assert denied.status_code == 400, denied.text
            target = tmp_path / "shared-clock"
            saved = client.post("/api/clock/dir", json={"path": str(target)}, headers=headers)
            assert saved.status_code == 200, saved.text
            body = saved.json()
            assert body["enabled"] is True
            assert "shared-clock" in body["clock_dir"]
            assert "git" in body
            slots = client.get("/api/clock/slots", headers=headers)
            assert slots.status_code == 200
            health = client.get("/api/health")
            assert "clock" in health.json()
    finally:
        if backup is None:
            if pointer.exists():
                pointer.unlink()
        else:
            pointer.write_text(backup, encoding="utf-8")


def test_watchlist_order_drives_query_rows():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        reset = client.put(
            "/api/watchlist",
            json={"items": [{"code": i.code_full} for i in WATCH_SEED]},
            headers=headers,
        )
        assert reset.status_code == 200
        original = [x["code6"] for x in reset.json()]
        assert original[0] == WATCH_SEED[0].code6
        reversed_codes = list(reversed(original))
        ordered = client.put("/api/watchlist/order", json={"codes": reversed_codes}, headers=headers)
        assert ordered.status_code == 200, ordered.text
        assert [x["code6"] for x in ordered.json()] == reversed_codes
        listed = client.get("/api/watchlist", headers=headers)
        assert [x["code6"] for x in listed.json()] == reversed_codes
        query = client.post("/api/query/run", json={}, headers=headers)
        assert query.status_code == 200
        assert [r["code6"] for r in query.json()["rows"]] == reversed_codes
        prefs = client.get("/api/query/prefs", headers=headers)
        keys = {x["key"]: x for x in prefs.json()["all"]}
        assert keys["turnover"]["default"] is False
        assert keys["mcap"]["default"] is False
        assert keys["pct60"]["default"] is False
        client.put("/api/watchlist/order", json={"codes": original}, headers=headers)


def test_custom_concepts_persist_and_filter():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        blocked = client.put(
            "/api/markets/concepts",
            json={"items": [{"label": "人工智能", "aliases": ["AI"]}]},
            headers=headers,
        )
        assert blocked.status_code == 400, blocked.text
        saved = client.put(
            "/api/markets/concepts",
            json={"items": [{"label": "直升机链", "aliases": "直升机"}]},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["items"][0]["label"] == "直升机链"
        listed = client.get("/api/markets/concepts", headers=headers)
        assert any(x["label"] == "直升机链" for x in listed.json()["items"])
        found = client.get("/api/markets/instruments?q=直升机链", headers=headers)
        assert found.status_code == 200
        assert any(x["code6"] == "600038" for x in found.json())
        client.put("/api/markets/concepts", json={"items": []}, headers=headers)
