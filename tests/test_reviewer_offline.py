from datetime import date, datetime

from fastapi.testclient import TestClient

from src.agents.reviewer import load_review_config, run_reviewer
from src.agents.watcher import _alert
from src.api.routes import market
from src.db import SessionLocal
from src.main import app
from src.models import Alert, User


def _auth(client: TestClient) -> dict:
    login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _user(db) -> User:
    user = db.query(User).filter_by(username="hanish").first()
    assert user is not None
    return user


def _make_alert(db, user, *, job_key, hit_date, hit_price=None, code6="600038"):
    rec = Alert(
        user_id=user.id,
        job_key=job_key,
        rule_id=job_key,
        code6=code6,
        title=f"{code6} · {job_key}",
        detail="test",
        status="open",
        severity="act",
        hit_price=hit_price,
        hit_date=hit_date,
        review_status="pending",
        created_at=datetime(2026, 9, 11, 10, 0, 0),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def test_reviewer_yaml_loads():
    cfg = load_review_config()
    assert "near-bottom" in cfg.bounce_jobs
    assert "near-target" in cfg.fade_jobs
    assert "holders-change" in cfg.info_jobs


def test_reviewer_four_edges_offline():
    with TestClient(app):
        db = SessionLocal()
        try:
            user = _user(db)
            db.query(Alert).filter_by(user_id=user.id).delete()
            db.commit()
            helpful = _make_alert(db, user, job_key="near-bottom", hit_date="2026-09-11", hit_price=26.0)
            noise = _make_alert(db, user, job_key="near-bottom", hit_date="2026-09-11", hit_price=28.0)
            skipped = _make_alert(db, user, job_key="holders-change", hit_date="2026-09-11")
            pending = _make_alert(db, user, job_key="near-bottom", hit_date="2026-09-15", hit_price=26.0)
            deferred = _make_alert(db, user, job_key="near-bottom", hit_date="2026-09-14", hit_price=26.0)
            fade = _make_alert(db, user, job_key="near-target", hit_date="2026-09-11", hit_price=28.0)
            out = run_reviewer(db, user, market, today=date(2026, 9, 15))
            assert out["count"] >= 4
            db.refresh(helpful)
            db.refresh(noise)
            db.refresh(skipped)
            db.refresh(pending)
            db.refresh(deferred)
            db.refresh(fade)
            assert helpful.review_status == "helpful"
            assert noise.review_status == "noise"
            assert skipped.review_status == "skipped"
            assert pending.review_status == "pending"
            assert deferred.review_status == "deferred"
            assert fade.review_status == "helpful"
            assert helpful.review_close is not None
        finally:
            db.close()


def test_watcher_writes_hit_price():
    with TestClient(app):
        db = SessionLocal()
        try:
            user = _user(db)
            payload = _alert(
                db,
                user.id,
                "near-bottom",
                "600038",
                "中直股份 · 接近底部",
                "test hit",
                persist=True,
                hit_price=26.86,
            )
            db.commit()
            assert payload["hit_price"] == 26.86
            rec = db.query(Alert).filter_by(user_id=user.id, job_key="near-bottom", code6="600038").order_by(Alert.id.desc()).first()
            assert rec is not None
            assert rec.hit_price == 26.86
            assert rec.review_status == "pending"
            assert rec.hit_date
        finally:
            db.close()


def test_review_api_run_and_list():
    with TestClient(app) as client:
        headers = _auth(client)
        listed = client.get("/api/monitor/reviews", headers=headers)
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert "pending" in body and "done" in body and "counts" in body
        ran = client.post("/api/monitor/review/run", headers=headers)
        assert ran.status_code == 200, ran.text
        assert "count" in ran.json()
        assert "counts" in ran.json()
