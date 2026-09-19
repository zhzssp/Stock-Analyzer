from fastapi.testclient import TestClient

from src.agents.watcher import run_watcher
from src.api.routes import market
from src.db import SessionLocal
from src.main import app
from src.models import User


def _auth(client: TestClient) -> dict:
    login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_policy_endpoint_and_health():
    with TestClient(app) as client:
        health = client.get("/api/health")
        policies = health.json()["agent"]["policies"]
        assert "watch_card" in policies["analyst"]["tools"]
        assert "watch_review" in policies["analyst"]["tools"]
        assert policies["researcher"]["inject_today_queue"] is True
        listed = client.get("/api/agent/policy")
        assert listed.status_code == 200
        assert listed.json()["analyst"]["rules"]


def test_decision_card_and_query_column():
    with TestClient(app) as client:
        headers = _auth(client)
        saved = client.put(
            "/api/watchlist/600038/card",
            json={"thesis": "航空主机", "buy_low": 24, "buy_high": 28, "reduce_price": 36, "cost": 25, "group": "观察"},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text
        body = saved.json()
        assert body["card_filled"] is True
        assert body["group"] == "观察"
        assert body["card"]["buy_high"] == 28

        prefs = client.put(
            "/api/query/prefs",
            json={"fields": ["name", "code", "price", "buy_high", "dist_buy"]},
            headers=headers,
        )
        assert prefs.status_code == 200
        query = client.post("/api/query/run", json={}, headers=headers)
        assert query.status_code == 200
        row = next(r for r in query.json()["rows"] if r["code6"] == "600038")
        assert row["buy_high"] == 28
        assert row["dist_buy"] is not None
        all_keys = [x["key"] for x in client.get("/api/query/prefs", headers=headers).json()["all"] if x.get("group") != "card"]
        client.put("/api/query/prefs", json={"fields": all_keys}, headers=headers)


def test_custom_rule_preview_and_persist():
    with TestClient(app) as client:
        headers = _auth(client)
        preview = client.post(
            "/api/monitor/rules/preview",
            json={"spec": {"name": "离底较近", "metric": "off_low", "op": "lte", "compare": "threshold", "value": 20, "schedule": "session"}},
            headers=headers,
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["count"] >= 1
        created = client.post(
            "/api/monitor/rules",
            json={"name": "离底较近", "enabled": True, "spec": {"metric": "off_low", "op": "lte", "compare": "threshold", "value": 20, "schedule": "eod"}},
            headers=headers,
        )
        assert created.status_code == 200, created.text
        rule_id = created.json()["id"]
        ran = client.post(f"/api/monitor/jobs/custom:{rule_id}/run", headers=headers)
        assert ran.status_code == 200, ran.text
        assert ran.json()["count"] >= 1
        blocked = client.post(
            "/api/monitor/rules",
            json={"name": "盘中股东", "spec": {"metric": "pe", "op": "lte", "value": 10, "schedule": "session", "compare": "threshold"}},
            headers=headers,
        )
        assert blocked.status_code == 400


def test_alert_status_and_session_skips_eod_jobs():
    with TestClient(app) as client:
        headers = _auth(client)
        client.post("/api/monitor/run", json={}, headers=headers)
        alerts = client.get("/api/alerts", headers=headers)
        assert alerts.status_code == 200
        items = alerts.json()
        assert items
        first = items[0]
        patched = client.patch(f"/api/alerts/{first['id']}", json={"status": "seen"}, headers=headers)
        assert patched.status_code == 200
        assert patched.json()["status"] == "seen"

        db = SessionLocal()
        try:
            user = db.query(User).filter_by(username="hanish").first()
            out = run_watcher(db, user, market, schedule="session")
        finally:
            db.close()
        assert "near-bottom" in out["ran"]
        assert "holders-change" not in out["ran"]
        assert "corp-events" not in out["ran"]
