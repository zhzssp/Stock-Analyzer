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
        assert ids["index:000001.SH"]["enabled"] is True
        assert ids["index:399001.SZ"]["enabled"] is True
        assert ids["index:899050.BJ"]["enabled"] is True
        assert ids["index:399001.SZ"]["label"] == "深证成指"
        assert ids["index:899050.BJ"]["label"] == "北证50"

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
        assert bj_row["yffy"] == 0.8

        cy = client.post("/api/query/run", json={"pool": "board:cy"}, headers=headers)
        cy_codes = {row["code6"] for row in cy.json()["rows"]}
        assert "300750" in cy_codes
        assert cy_codes >= {"300750", "300274", "300760"}
        assert all(code.startswith("300") for code in cy_codes)

        client.put("/api/watchlist", json={"items": [{"code": i.code_full} for i in WATCH_SEED]}, headers=headers)
        watch = client.post("/api/query/run", json={"pool": "watch"}, headers=headers)
        watch_codes = {row["code6"] for row in watch.json()["rows"]}
        assert "600038" in watch_codes
        assert "430017" not in watch_codes

        exported = client.post("/api/query/export", json={"pool": "exchange:bj"}, headers=headers)
        assert exported.status_code == 200
        assert "北交所全部" in exported.json()["filename"] or exported.json()["pool"] == "北交所全部"

        sse = client.get("/api/markets/pools/index:000001.SH/instruments", headers=headers)
        assert sse.status_code == 200
        assert sse.json()["label"] == "上证指数"
        sse_codes = {x["code6"] for x in sse.json()["items"]}
        assert sse_codes == {"600038", "600893", "600129", "601166", "600519"}
        assert "688001" not in sse_codes
        assert all(x["exchange"] == "SH" for x in sse.json()["items"])

        sz_idx = client.post("/api/query/run", json={"pool": "index:399001.SZ"}, headers=headers)
        assert sz_idx.status_code == 200
        sz_codes = {row["code6"] for row in sz_idx.json()["rows"]}
        assert sz_codes == {"000725", "000001", "002230", "000768"}
        assert "300750" not in sz_codes
        assert sz_idx.json()["pool"] == "深证成指"

        bj_idx = client.post("/api/query/export", json={"pool": "index:899050.BJ"}, headers=headers)
        assert bj_idx.status_code == 200
        assert bj_idx.json()["pool"] == "北证50"
        assert "北证50" in bj_idx.json()["filename"]
        assert "北交所全部" not in bj_idx.json()["filename"]
        bj_codes = {row["code6"] for row in client.post("/api/query/run", json={"pool": "index:899050.BJ"}, headers=headers).json()["rows"]}
        assert bj_codes == {"430017", "830799"}
        assert "833533" not in bj_codes


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
