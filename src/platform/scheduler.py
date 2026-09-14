from __future__ import annotations

from src.db import SessionLocal
from src.models import User


def start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        return None

    from src.agents.watcher import run_watcher
    from src.api.routes import market

    def _tick(job_key: str | None = None) -> None:
        db = SessionLocal()
        try:
            for user in db.query(User).all():
                run_watcher(db, user, market, job_key)
        finally:
            db.close()

    sched = BackgroundScheduler(timezone="Asia/Shanghai")
    sched.add_job(_tick, CronTrigger(minute="*/5", hour="9-15", day_of_week="mon-fri"), args=["near-bottom"], id="session-tick")
    sched.add_job(_tick, CronTrigger(hour=20, minute=20, day_of_week="mon-fri"), id="eod-scan")
    sched.start()
    return sched
