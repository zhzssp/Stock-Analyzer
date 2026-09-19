from fastapi.testclient import TestClient

from src.db import SessionLocal
from src.main import app
from src.models import Alert, Snapshot, User


def _auth(client: TestClient) -> dict:
    login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_column_prefs_drive_query_and_restore():
    with TestClient(app) as client:
        headers = _auth(client)
        prefs = client.get("/api/query/prefs", headers=headers)
        assert prefs.status_code == 200
        all_keys = [x["key"] for x in prefs.json()["all"]]
        assert "low_long" in all_keys
        assert "target" in all_keys

        saved = client.put(
            "/api/query/prefs",
            json={"fields": ["name", "code", "price", "low1y", "target"]},
            headers=headers,
        )
        assert saved.status_code == 200
        assert saved.json()["fields"] == ["name", "code", "price", "low1y", "target"]

        query = client.post("/api/query/run", json={}, headers=headers)
        assert query.status_code == 200
        keys = [f["key"] for f in query.json()["fields"]]
        assert keys == ["name", "code", "price", "low1y", "target"]
        row = next(r for r in query.json()["rows"] if r["code6"] == "600038")
        assert row["low1y"] == 24.6
        assert row["target"] == 36.9
        assert "yffy" not in row

        restore = client.put("/api/query/prefs", json={"fields": all_keys}, headers=headers)
        assert restore.status_code == 200


def test_watcher_jobs_alerts_and_disabled_slots():
    with TestClient(app) as client:
        headers = _auth(client)
        jobs = client.get("/api/monitor/jobs", headers=headers)
        assert jobs.status_code == 200
        by_key = {j["job_key"]: j for j in jobs.json()}
        assert by_key["holders-change"]["enabled"] is True
        assert by_key["capital-flow"]["enabled"] is True
        assert by_key["corp-events"]["enabled"] is True
        assert by_key["near-bottom"]["enabled"] is True
        assert by_key["near-target"]["enabled"] is True
        assert by_key["near-bottom"]["params"]["off_low_max"] == 8
        assert by_key["futures"]["enabled"] is False
        assert "期货" in by_key["futures"]["reason"]

        blocked = client.post(
            "/api/monitor/jobs/futures/toggle",
            json={"enabled": True},
            headers=headers,
        )
        assert blocked.status_code == 409

        db = SessionLocal()
        try:
            user = db.query(User).filter_by(username="hanish").first()
            db.query(Alert).filter_by(user_id=user.id).delete()
            db.commit()
        finally:
            db.close()

        ran = client.post("/api/monitor/run", json={}, headers=headers)
        assert ran.status_code == 200
        body = ran.json()
        assert "capital-flow" in body["ran"]
        assert body["count"] >= 1
        titles = " ".join(h["title"] for h in body["hits"])
        assert "资金" in titles or "事件" in titles or "分红" in titles

        alerts = client.get("/api/alerts", headers=headers)
        assert alerts.status_code == 200
        assert len(alerts.json()) >= 1

        db = SessionLocal()
        try:
            user = db.query(User).filter_by(username="hanish").first()
            row = db.query(Snapshot).filter_by(user_id=user.id, code6="600038", kind="holders").first()
            if row:
                row.payload = '{"holders": "旧股东快照"}'
            else:
                db.add(Snapshot(user_id=user.id, code6="600038", kind="holders", payload='{"holders": "旧股东快照"}'))
            db.query(Alert).filter_by(user_id=user.id, job_key="holders-change", code6="600038").delete()
            db.commit()
        finally:
            db.close()

        again = client.post("/api/monitor/jobs/holders-change/run", json={}, headers=headers)
        assert again.status_code == 200
        assert any(h["job_key"] == "holders-change" for h in again.json()["hits"])
