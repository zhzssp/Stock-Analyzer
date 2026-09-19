from __future__ import annotations

from sqlalchemy.orm import Session

from src.models import Alert, WatchItem


def today_queue(db: Session, user_id: int, limit: int = 20) -> list[dict]:
    items = (
        db.query(Alert)
        .filter_by(user_id=user_id, status="open")
        .order_by(Alert.id.desc())
        .limit(80)
        .all()
    )
    act = [a for a in items if a.severity == "act"]
    watch = [a for a in items if a.severity != "act"]
    ordered = act + watch
    names = {w.code6: w.name for w in db.query(WatchItem).filter_by(user_id=user_id).all()}
    out = []
    for rec in ordered[:limit]:
        out.append(
            {
                "id": rec.id,
                "kind": "alert",
                "job_key": rec.job_key,
                "rule_id": rec.rule_id or rec.job_key,
                "code6": rec.code6,
                "name": names.get(rec.code6, ""),
                "title": rec.title,
                "detail": rec.detail,
                "severity": rec.severity or "watch",
                "status": rec.status or "open",
                "created_at": rec.created_at.isoformat() if rec.created_at else None,
            }
        )
    return out
