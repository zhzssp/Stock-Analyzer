from datetime import date

from fastapi.testclient import TestClient

from src.main import app
from src.market.calendar import is_trading_day, prev_trading_day
from src.market.client import MarketClient, resolve_instruments
from src.tools.base import ToolContext
from src.tools.disclosure_tools import corp_disclosure, limit_review, market_breadth


def test_trading_calendar_offline():
    market = MarketClient()
    assert is_trading_day("20260918", market)
    assert not is_trading_day("20260919", market)  # Saturday
    prev = prev_trading_day("20260921", market)
    assert prev == "20260918"


def test_disclosure_and_limit_client():
    market = MarketClient()
    inst = resolve_instruments(["600038.SH"], market)[0]
    ann = market.announcements(inst)
    assert ann and "合同" in ann[0]["title"]
    perf = market.limit_performance(resolve_instruments(["300274"], market)[0])
    assert perf[0]["direction"] == 1
    assert "300274" in market.dragon_tiger_codes()
    tops = market.sector_funds_top("industry", 2)
    assert tops[0]["name"] == "电子"


def test_disclosure_tools():
    market = MarketClient()
    inst = resolve_instruments(["002230.SZ"], market)[0]
    ctx = ToolContext(user_id=0, db=None, market=market, engine=None)
    disc = corp_disclosure({"code": inst.code_full}, ctx)
    assert disc.ok
    assert disc.data[0]["interactive_qa"]
    breadth = market_breadth({"limit": 2}, ctx)
    assert breadth.ok
    assert breadth.data["dragon_tiger_count"] >= 3
    assert breadth.data["sector_funds_industry"][0]["name"] == "电子"
    review = limit_review({"code": "300274.SZ"}, ctx)
    assert review.ok
    assert review.data[0]["limit_perf"]


def test_monitor_phase2_jobs():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        jobs = client.get("/api/monitor/jobs", headers=headers)
        by_key = {j["job_key"]: j for j in jobs.json()}
        assert by_key["corp-disclosure"]["enabled"] is True
        assert by_key["limit-review"]["enabled"] is True
        assert by_key["dragon-tiger"]["enabled"] is True
        assert by_key["capital-flow"]["params"]["use_prev_day"] is True

        from src.db import SessionLocal
        from src.models import Alert, User

        db = SessionLocal()
        try:
            user = db.query(User).filter_by(username="hanish").first()
            db.query(Alert).filter_by(user_id=user.id, job_key="dragon-tiger").delete()
            db.commit()
        finally:
            db.close()

        ran = client.post("/api/monitor/jobs/dragon-tiger/run", json={}, headers=headers)
        assert ran.status_code == 200
        assert any(h["job_key"] == "dragon-tiger" and h["code6"] == "300274" for h in ran.json()["hits"])
