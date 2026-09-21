from fastapi.testclient import TestClient

from src.main import app
from src.market.capability_gaps import gap_catalog
from src.query.engine import QueryEngine
from src.query.registry import registry
from src.market.client import MarketClient, resolve_instruments


def test_phase3_gap_catalog():
    gaps = gap_catalog()
    ids = {g["id"] for g in gaps}
    assert {"U1", "U2", "U3", "U5", "U6", "P3-1m", "P3-fund"} <= ids
    north = next(g for g in gaps if g.get("field") == "northbound")
    assert "北向" in north["reason"]


def test_northbound_field_metadata():
    spec = registry.get("northbound")
    assert spec.default is False
    assert spec.unavailable
    fields = QueryEngine(MarketClient()).fields()
    north = next(f for f in fields if f["key"] == "northbound")
    assert north["unavailable"] == spec.unavailable


def test_taxonomy_exposes_phase3_gaps():
    with TestClient(app) as client:
        tax = client.get("/api/markets/taxonomy")
        assert tax.status_code == 200
        body = tax.json()
        assert body["northbound"] == "未接入"
        assert body["phase3_note"]
        assert len(body["gaps"]) >= 7
        assert any(g["id"] == "U1" for g in body["gaps"])


def test_gray_monitor_jobs_remain_disabled():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        jobs = client.get("/api/monitor/jobs", headers=headers)
        by_key = {j["job_key"]: j for j in jobs.json()}
        assert by_key["futures"]["enabled"] is False
        assert by_key["futures"]["reason"]
        assert by_key["news"]["enabled"] is False
        assert by_key["policy"]["enabled"] is False


def test_northbound_stays_empty_when_requested():
    engine = QueryEngine(MarketClient())
    row = engine.run(resolve_instruments(["600038.SH"], MarketClient()), ["code", "northbound"])[0]
    assert row["northbound"] is None
