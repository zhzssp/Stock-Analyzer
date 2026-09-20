from __future__ import annotations

from src.db import SessionLocal
from src.models import User, WatchItem


def start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError:
        return None

    from src.agents.reviewer import run_reviewer
    from src.agents.watcher import run_watcher
    from src.api.routes import market
    from src.market.client import resolve_instruments
    from src.market.clock import align_quotes, configured_clock_dir, write_universe
    from src.platform.storage import enforce_all

    def _clock_tick() -> None:
        root = configured_clock_dir()
        if root is None:
            return
        db = SessionLocal()
        try:
            for user in db.query(User).all():
                items = db.query(WatchItem).filter_by(user_id=user.id).all()
                write_universe(root, user.username, [i.code6 for i in items])
                insts = resolve_instruments([i.code_full for i in items], market) if items else []
                if insts:
                    align_quotes(market, insts, writer=user.username, clock_dir=root)
        finally:
            db.close()

    def _tick(schedule: str | None = None) -> None:
        db = SessionLocal()
        try:
            for user in db.query(User).all():
                run_watcher(db, user, market, schedule=schedule)
                if schedule == "eod":
                    run_reviewer(db, user, market)
            if schedule == "eod":
                enforce_all(db)
        finally:
            db.close()

    sched = BackgroundScheduler(timezone="Asia/Shanghai")
    sched.add_job(_tick, CronTrigger(minute="*/5", hour="9-15", day_of_week="mon-fri"), kwargs={"schedule": "session"}, id="session-tick")
    sched.add_job(_tick, CronTrigger(hour=20, minute=20, day_of_week="mon-fri"), kwargs={"schedule": "eod"}, id="eod-scan")
    sched.add_job(_clock_tick, CronTrigger(minute="*", hour="9-15", day_of_week="mon-fri"), id="clock-align")
    sched.start()
    return sched
