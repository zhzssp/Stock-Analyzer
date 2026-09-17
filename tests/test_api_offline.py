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
        assert any(x["code6"] == "688001" for x in kc.json())
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

        cy = client.get("/api/markets/instruments?market=cy")
        assert cy.status_code == 200
        assert {x["code6"] for x in cy.json()} == {"300750"}

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
