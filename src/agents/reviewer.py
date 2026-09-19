from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from typing import Any

import yaml
from sqlalchemy.orm import Session

from src.agents.rules import _num, parse_json
from src.config import ROOT
from src.market.client import MarketClient, resolve_instruments
from src.models import Alert, User, UserRule, WatchItem

POLICY_PATH = ROOT / "config" / "agents" / "reviewer.yaml"
REVIEW_STATUSES = ("pending", "helpful", "noise", "mixed", "skipped", "deferred")
REVIEW_LABELS = {
    "pending": "待复盘",
    "helpful": "次日同向",
    "noise": "次日反向",
    "mixed": "波动不足",
    "skipped": "不按涨跌",
    "deferred": "尚无次日收盘",
}


@dataclass(frozen=True)
class ReviewConfig:
    up_pct: float = 1.0
    down_pct: float = 1.0
    bounce_jobs: tuple[str, ...] = ("near-bottom",)
    fade_jobs: tuple[str, ...] = ("near-target",)
    info_jobs: tuple[str, ...] = ("holders-change", "fund-holding", "corp-events", "capital-flow")
    bounce_metrics: tuple[str, ...] = ("off_low", "dist_buy")
    fade_metrics: tuple[str, ...] = ("dist_reduce",)


def _as_tuple(value: Any, fallback: tuple[str, ...]) -> tuple[str, ...]:
    if not value:
        return fallback
    items = tuple(str(x) for x in value if str(x).strip())
    return items or fallback


@lru_cache(maxsize=1)
def load_review_config() -> ReviewConfig:
    fallback = ReviewConfig()
    if not POLICY_PATH.exists():
        return fallback
    raw = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        return fallback
    return ReviewConfig(
        up_pct=float(raw.get("up_pct") or fallback.up_pct),
        down_pct=float(raw.get("down_pct") or fallback.down_pct),
        bounce_jobs=_as_tuple(raw.get("bounce_jobs"), fallback.bounce_jobs),
        fade_jobs=_as_tuple(raw.get("fade_jobs"), fallback.fade_jobs),
        info_jobs=_as_tuple(raw.get("info_jobs"), fallback.info_jobs),
        bounce_metrics=_as_tuple(raw.get("bounce_metrics"), fallback.bounce_metrics),
        fade_metrics=_as_tuple(raw.get("fade_metrics"), fallback.fade_metrics),
    )


def reload_review_config() -> None:
    load_review_config.cache_clear()


def _hit_day(rec: Alert) -> date | None:
    raw = (rec.hit_date or "").strip()
    if raw:
        try:
            return date.fromisoformat(raw[:10])
        except ValueError:
            pass
    if rec.created_at:
        return rec.created_at.date()
    return None


def _bar_day(row: dict) -> date | None:
    raw = row.get("d") or row.get("date") or row.get("t")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _next_close(market: MarketClient, code6: str, hit_on: date) -> tuple[date | None, float | None]:
    insts = resolve_instruments([code6], market)
    if not insts:
        return None, None
    best: tuple[date, float] | None = None
    for row in market.history(insts[0]) or []:
        day = _bar_day(row)
        close = _num(row.get("c") if row.get("c") is not None else row.get("close"))
        if day is None or close is None or day <= hit_on:
            continue
        if best is None or day < best[0]:
            best = (day, close)
    if best is None:
        return None, None
    return best


def _custom_direction(db: Session, user_id: int, job_key: str, cfg: ReviewConfig) -> str | None:
    if not job_key.startswith("custom:"):
        return None
    try:
        rid = int(job_key.split(":", 1)[1])
    except ValueError:
        return None
    row = db.query(UserRule).filter_by(id=rid, user_id=user_id).first()
    spec = parse_json(row.spec if row else None, {})
    if not isinstance(spec, dict):
        spec = {}
    metric = str(spec.get("metric") or "")
    op = str(spec.get("op") or "lte")
    if metric in cfg.bounce_metrics:
        return "bounce"
    if metric in cfg.fade_metrics:
        return "fade"
    if op == "gte":
        return "fade"
    return "bounce"


def _direction(db: Session, rec: Alert, cfg: ReviewConfig) -> str | None:
    job_key = rec.job_key or rec.rule_id or ""
    base = job_key.split(":")[0] if job_key.startswith("custom:") else job_key
    if job_key in cfg.info_jobs or base in cfg.info_jobs:
        return "info"
    if job_key in cfg.bounce_jobs or base in cfg.bounce_jobs:
        return "bounce"
    if job_key in cfg.fade_jobs or base in cfg.fade_jobs:
        return "fade"
    custom = _custom_direction(db, rec.user_id, job_key, cfg)
    if custom:
        return custom
    if rec.hit_price is not None:
        return "bounce"
    return "info"


def _score(direction: str, ret: float, cfg: ReviewConfig) -> str:
    up = abs(cfg.up_pct)
    down = abs(cfg.down_pct)
    if direction == "fade":
        if ret <= -up:
            return "helpful"
        if ret >= down:
            return "noise"
        return "mixed"
    if ret >= up:
        return "helpful"
    if ret <= -down:
        return "noise"
    return "mixed"


def _stamp(rec: Alert, status: str, *, close: float | None = None, ret: float | None = None, note: str = "") -> None:
    rec.review_status = status
    rec.review_close = close
    rec.review_return_pct = ret
    rec.review_note = note
    rec.reviewed_at = datetime.now() if status != "pending" else None


def alert_review_dict(rec: Alert, names: dict[str, str] | None = None) -> dict:
    status = rec.review_status or "pending"
    return {
        "id": rec.id,
        "job_key": rec.job_key,
        "rule_id": rec.rule_id or rec.job_key,
        "code6": rec.code6,
        "name": (names or {}).get(rec.code6, ""),
        "title": rec.title,
        "detail": rec.detail,
        "status": rec.status or "open",
        "severity": rec.severity or "watch",
        "created_at": rec.created_at.isoformat() if rec.created_at else None,
        "hit_price": rec.hit_price,
        "hit_date": rec.hit_date or "",
        "review_status": status,
        "review_label": REVIEW_LABELS.get(status, status),
        "review_return_pct": rec.review_return_pct,
        "review_close": rec.review_close,
        "reviewed_at": rec.reviewed_at.isoformat() if rec.reviewed_at else None,
        "review_note": rec.review_note or "",
    }


def reviews_payload(db: Session, user_id: int, limit: int = 80) -> dict:
    rows = db.query(Alert).filter_by(user_id=user_id).order_by(Alert.id.desc()).limit(limit).all()
    names = {w.code6: w.name for w in db.query(WatchItem).filter_by(user_id=user_id).all()}
    items = [alert_review_dict(r, names) for r in rows]
    pending = [x for x in items if x["review_status"] in {"pending", "deferred"}]
    done = [x for x in items if x["review_status"] not in {"pending", "deferred"}]
    counts = {key: 0 for key in REVIEW_STATUSES}
    by_job: dict[str, dict[str, int]] = {}
    for item in items:
        status = item["review_status"]
        counts[status] = counts.get(status, 0) + 1
        job = item["job_key"] or ""
        bucket = by_job.setdefault(job, {key: 0 for key in REVIEW_STATUSES})
        bucket[status] = bucket.get(status, 0) + 1
    return {"pending": pending, "done": done, "counts": counts, "by_job": by_job, "items": items}


def recent_review_lines(db: Session, user_id: int, limit: int = 8) -> list[str]:
    rows = (
        db.query(Alert)
        .filter(Alert.user_id == user_id, Alert.review_status.in_(("helpful", "noise", "mixed", "skipped")))
        .order_by(Alert.reviewed_at.desc(), Alert.id.desc())
        .limit(limit)
        .all()
    )
    names = {w.code6: w.name for w in db.query(WatchItem).filter_by(user_id=user_id).all()}
    lines = []
    for rec in rows:
        label = REVIEW_LABELS.get(rec.review_status or "", rec.review_status)
        name = names.get(rec.code6) or rec.code6
        ret = rec.review_return_pct
        ret_s = f"{ret:+.2f}%" if isinstance(ret, (int, float)) else "—"
        lines.append(f"{name} {rec.job_key} {label} 次日 {ret_s}")
    return lines


def run_reviewer(db: Session, user: User, market: MarketClient, today: date | None = None) -> dict:
    cfg = load_review_config()
    today = today or date.today()
    rows = (
        db.query(Alert)
        .filter(Alert.user_id == user.id, Alert.review_status.in_(("pending", "deferred")))
        .order_by(Alert.id.asc())
        .all()
    )
    changed: list[dict] = []
    for rec in rows:
        direction = _direction(db, rec, cfg)
        if direction == "info":
            _stamp(rec, "skipped", note="信息不按涨跌打分")
            changed.append(alert_review_dict(rec))
            continue
        hit_on = _hit_day(rec)
        if hit_on is None or hit_on >= today:
            _stamp(rec, "pending", note="未到次日")
            rec.reviewed_at = None
            continue
        if rec.hit_price is None:
            _stamp(rec, "deferred", note="缺少命中价")
            changed.append(alert_review_dict(rec))
            continue
        close_day, close = _next_close(market, rec.code6, hit_on)
        if close_day is None or close is None:
            _stamp(rec, "deferred", note="尚无下一根交易日收盘")
            changed.append(alert_review_dict(rec))
            continue
        ret = (close - rec.hit_price) / rec.hit_price * 100 if rec.hit_price else None
        if ret is None:
            _stamp(rec, "deferred", note="无法计算涨跌")
            changed.append(alert_review_dict(rec))
            continue
        status = _score(direction, ret, cfg)
        _stamp(
            rec,
            status,
            close=close,
            ret=round(ret, 4),
            note=f"{close_day.isoformat()} 收盘 {close}",
        )
        changed.append(alert_review_dict(rec))
    db.commit()
    from src.platform.bus import bus

    counts = {key: 0 for key in REVIEW_STATUSES}
    for item in changed:
        status = item.get("review_status") or ""
        if status in counts:
            counts[status] += 1
    bus.publish(
        "watch.reviewed",
        {"user_id": user.id, "count": len(changed), "counts": counts},
        source_agent="reviewer",
        idempotency_key=f"{user.id}:review:{today.isoformat()}",
    )
    return {"count": len(changed), "counts": counts, "items": changed}
