import time

from fastapi.testclient import TestClient

from src.main import app
from src.market.fixtures import WATCH_SEED


def _auth(client: TestClient) -> dict:
    login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
    assert login.status_code == 200
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_pools_catalog_and_exchange_query_export():
    with TestClient(app) as client:
        headers = _auth(client)
        pools = client.get("/api/markets/pools")
        assert pools.status_code == 200
        ids = {p["id"]: p for p in pools.json()["pools"]}
        assert ids["watch"]["enabled"] is True
        assert ids["exchange:sh"]["label"] == "沪市全部"
        assert ids["exchange:sz"]["label"] == "深市全部"
        assert ids["exchange:bj"]["label"] == "北交所全部"
        assert ids["board:cy"]["label"] == "创业板全部"
        assert ids["index:399001.SZ"]["enabled"] is False
        assert ids["index:899050.BJ"]["enabled"] is False

        sh = client.get("/api/markets/pools/exchange:sh/instruments", headers=headers)
        assert sh.status_code == 200
        assert sh.json()["sample"] is True
        assert all(x["exchange"] == "SH" for x in sh.json()["items"])
        assert "上证指数" not in sh.json()["label"]

        sz = client.post("/api/query/run", json={"pool": "exchange:sz"}, headers=headers)
        assert sz.status_code == 200
        assert sz.json()["sample"] is True
        assert all(row["code"].endswith(".SZ") for row in sz.json()["rows"])
        assert any(row["code6"] == "000725" for row in sz.json()["rows"])
        assert not any(row["code"].endswith(".SH") for row in sz.json()["rows"])

        bj = client.post("/api/query/run", json={"pool": "exchange:bj"}, headers=headers)
        names = {row["name"] for row in bj.json()["rows"]}
        assert "星昊医药" in names
        assert "中直股份" not in names
        bj_row = next(row for row in bj.json()["rows"] if row["code6"] == "430017")
        assert bj_row["yffy"] is None

        cy = client.post("/api/query/run", json={"pool": "board:cy"}, headers=headers)
        assert {row["code6"] for row in cy.json()["rows"]} == {"300750"}

        client.put("/api/watchlist", json={"items": [{"code": i.code_full} for i in WATCH_SEED]}, headers=headers)
        watch = client.post("/api/query/run", json={"pool": "watch"}, headers=headers)
        watch_codes = {row["code6"] for row in watch.json()["rows"]}
        assert "600038" in watch_codes
        assert "430017" not in watch_codes

        exported = client.post("/api/query/export", json={"pool": "exchange:bj"}, headers=headers)
        assert exported.status_code == 200
        assert "北交所全部" in exported.json()["filename"] or exported.json()["pool"] == "北交所全部"

        idx = ids["index:000001.SH"]
        listed = client.get("/api/markets/pools/index:000001.SH/instruments", headers=headers)
        if idx["enabled"]:
            assert listed.status_code == 200
            assert listed.json()["items"]
        else:
            assert listed.status_code == 409
            assert client.post("/api/query/run", json={"pool": "index:399001.SZ"}, headers=headers).status_code == 409


def test_large_pool_uses_job():
    with TestClient(app) as client:
        headers = _auth(client)
        started = client.post("/api/query/run", json={"pool": "exchange:sh", "async_mode": True}, headers=headers)
        assert started.status_code == 200
        body = started.json()
        assert body["job_id"]
        assert body["status"] in {"running", "done"}
        job = client.get(f"/api/query/jobs/{body['job_id']}", headers=headers)
        assert job.status_code == 200
        for _ in range(40):
            data = client.get(f"/api/query/jobs/{body['job_id']}", headers=headers).json()
            if data["status"] == "done":
                assert data["rows"]
                assert all(row["code"].endswith(".SH") for row in data["rows"])
                return
            if data["status"] == "error":
                raise AssertionError(data["error"])
            time.sleep(0.05)
        raise AssertionError("job did not finish")
