from fastapi.testclient import TestClient

from src.main import app
from src.market.client import MarketClient, resolve_instruments
from src.query.engine import QueryEngine


def test_official_concept_filter():
    market = MarketClient()
    rows = market.search(q="", market="all", limit=50, official_concept="人工智能")
    codes = {x["code6"] for x in rows}
    assert codes == {"002230", "688981"}
    assert all(x.get("concept_source") == "offline-fixture" for x in rows)


def test_indicators_and_x_price():
    market = MarketClient()
    engine = QueryEngine(market)
    insts = resolve_instruments(["600038.SH", "002230.SZ"], market)
    rows = engine.run(
        insts,
        field_keys=["name", "pct3", "pct5", "pct10", "x_price"],
        x_date="2026-09-12",
    )
    by = {r["code6"]: r for r in rows}
    assert by["600038"]["pct3"] == 2.4
    assert by["002230"]["pct10"] == 8.2
    assert by["600038"]["x_price"] is not None


def test_limit_pool_offline():
    market = MarketClient()
    assert "300274" in market.limit_pool_codes("up")
    assert "002415" in market.limit_pool_codes("down")


def test_bj_finance_offline():
    market = MarketClient()
    engine = QueryEngine(market)
    rows = engine.run(resolve_instruments(["430017.BJ"], market), field_keys=["name", "yffy", "zgb"])
    assert rows[0]["yffy"] == 0.8
    assert rows[0]["zgb"] == 8.6


def test_monitor_limit_jobs_exist():
    from src.db import SessionLocal
    from src.models import Alert, User

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        jobs = client.get("/api/monitor/jobs", headers=headers)
        by_key = {j["job_key"]: j for j in jobs.json()}
        assert by_key["limit-up"]["enabled"] is True
        assert by_key["limit-down"]["enabled"] is True

        db = SessionLocal()
        try:
            user = db.query(User).filter_by(username="hanish").first()
            db.query(Alert).filter_by(user_id=user.id, job_key="limit-up").delete()
            db.commit()
        finally:
            db.close()

        ran = client.post("/api/monitor/jobs/limit-up/run", json={}, headers=headers)
        assert ran.status_code == 200
        hits = ran.json()["hits"]
        assert any(h["job_key"] == "limit-up" and h["code6"] == "300274" for h in hits)
