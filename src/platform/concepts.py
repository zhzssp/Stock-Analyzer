from __future__ import annotations

import json

from sqlalchemy.orm import Session

from src.market.taxonomy import extra_book, normalize_custom_concepts
from src.models import ConceptPref, User


def load_items(db: Session, user: User | None) -> list[dict]:
    if user is None:
        return []
    row = db.query(ConceptPref).filter_by(user_id=user.id).first()
    if not row or not row.payload:
        return []
    try:
        raw = json.loads(row.payload)
    except json.JSONDecodeError:
        return []
    try:
        return normalize_custom_concepts(raw)
    except ValueError:
        return []


def extra_for(db: Session, user: User | None) -> dict[str, tuple[str, ...]]:
    return extra_book(load_items(db, user))


def save_items(db: Session, user: User, items: list[dict]) -> list[dict]:
    cleaned = normalize_custom_concepts(items)
    payload = json.dumps(cleaned, ensure_ascii=False)
    row = db.query(ConceptPref).filter_by(user_id=user.id).first()
    if row:
        row.payload = payload
    else:
        db.add(ConceptPref(user_id=user.id, payload=payload))
    db.commit()
    return cleaned
