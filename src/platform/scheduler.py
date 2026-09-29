from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from src.config import settings
from src.db import SessionLocal
from src.models import User, WatchItem


def log_scheduler_error(what: str, exc: BaseException) -> None:
    """调度出错必须留痕：以前一处异常会让整轮（含复盘、配额清理）静默不跑，且没有任何记录。"""
    try:
        log_dir = settings.data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with (log_dir / "scheduler.log").open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {what}: {type(exc).__name__}: {exc}\n")
    except Exception:  # noqa: BLE001 - 记日志这件事本身不能再抛
        pass


def eod_marker_path():
    return settings.data_dir / "last_eod.json"


def last_eod_day() -> str:
    """上次成功跑完日终（含复盘）的日期，用来判断今天是不是被错过了。"""
    try:
        return str(json.loads(eod_marker_path().read_text(encoding="utf-8")).get("day") or "")
    except Exception:  # noqa: BLE001
        return ""


def mark_eod_done(day: str | None = None) -> None:
    try:
        path = eod_marker_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "day": day or date.today().isoformat(),
                    "at": datetime.now().isoformat(timespec="seconds"),
                }
            ),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass


def start_scheduler():
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
    except ImportError as exc:
        # 以前静默返回 None：监控、复盘、配额清理全部停摆，而界面上看不出任何异常
        log_scheduler_error("调度器启动失败（缺少 apscheduler），监控与复盘不会自动运行", exc)
        return None

    from src.agents.reviewer import run_reviewer
    from src.agents.watcher import run_watcher
    from src.api.routes import market
    from src.market.client import resolve_instruments
    from src.market.clock import align_quotes, configured_clock_dir, write_universe
    from src.platform.storage import enforce_all

    def _clock_tick() -> None:
        # 运行中切离线/换证书池时 routes.market 会被整体替换，每次取最新的
        from src.api.routes import market as live_market

        market = live_market
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
        # 同上：启动时抓到的 client 可能已经被换掉（ensure_market / 重载证书池）
        from src.api.routes import market as live_market

        market = live_market
        db = SessionLocal()
        try:
            for user in db.query(User).all():
                # 一个用户出错不能拖垮其他用户，也不能让复盘 / 配额清理跟着不跑
                try:
                    run_watcher(db, user, market, schedule=schedule)
                except Exception as exc:  # noqa: BLE001
                    log_scheduler_error(f"run_watcher user={getattr(user, 'username', '?')}", exc)
                if schedule == "eod":
                    try:
                        run_reviewer(db, user, market)
                    except Exception as exc:  # noqa: BLE001
                        log_scheduler_error(f"run_reviewer user={getattr(user, 'username', '?')}", exc)
            if schedule == "eod":
                try:
                    enforce_all(db)
                except Exception as exc:  # noqa: BLE001
                    log_scheduler_error("enforce_all", exc)
                mark_eod_done()
        finally:
            db.close()

    from src.config import settings

    # 频率可配：低性能机器或额度吃紧时把这两个调大，能明显降 CPU 与请求量。
    session_minutes = max(1, int(getattr(settings, "monitor_session_minutes", 0) or 5))
    clock_minutes = max(1, int(getattr(settings, "clock_align_minutes", 0) or 1))
    session_trigger = CronTrigger(minute=f"*/{session_minutes}", hour="9-15", day_of_week="mon-fri")
    clock_trigger = CronTrigger(minute=f"*/{clock_minutes}", hour="9-15", day_of_week="mon-fri")

    sched = BackgroundScheduler(timezone="Asia/Shanghai")
    # misfire_grace_time：默认只有 1 秒 —— 本机软件关机/没启动就永久错过。
    # coalesce + max_instances：上一轮没跑完时不叠新一轮。
    sched.add_job(
        _tick, session_trigger, kwargs={"schedule": "session"}, id="session-tick",
        misfire_grace_time=1800, coalesce=True, max_instances=1,
    )
    sched.add_job(
        _tick, CronTrigger(hour=20, minute=20, day_of_week="mon-fri"), kwargs={"schedule": "eod"}, id="eod-scan",
        misfire_grace_time=7200, coalesce=True, max_instances=1,
    )
    sched.add_job(
        _clock_tick, clock_trigger, id="clock-align",
        misfire_grace_time=1800, coalesce=True, max_instances=1,
    )
    # 20:20 没开机就永久错过 —— 启动时若今天（交易日）还没跑过日终，延迟一会儿补跑一次。
    try:
        from src.market.calendar import is_trading_day

        today = date.today().isoformat()
        if last_eod_day() != today and is_trading_day(today.replace("-", ""), market):
            sched.add_job(
                _tick,
                "date",
                run_date=datetime.now() + timedelta(seconds=20),
                kwargs={"schedule": "eod"},
                id="eod-catchup",
                misfire_grace_time=3600,
            )
    except Exception as exc:  # noqa: BLE001
        log_scheduler_error("eod 补跑判断", exc)
    sched.start()
    return sched
