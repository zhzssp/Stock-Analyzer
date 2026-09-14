from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy.orm import Session

from src.models import AgentSession, User


def _loads(raw: str | None) -> list[dict]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def session_payload(row: AgentSession) -> dict:
    return {
        "id": row.id,
        "title": row.title,
        "agent": row.agent,
        "messages": _loads(row.messages),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def get_session(db: Session, user: User, session_id: int | None) -> AgentSession | None:
    if not session_id:
        return None
    return db.query(AgentSession).filter_by(id=session_id, user_id=user.id).first()


def create_session(db: Session, user: User, agent: str, title: str) -> AgentSession:
    row = AgentSession(user_id=user.id, agent=agent, title=(title or "新对话")[:128], messages="[]")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def append_turns(db: Session, row: AgentSession, turns: list[dict], agent: str | None = None) -> AgentSession:
    messages = _loads(row.messages)
    messages.extend(turns)
    row.messages = json.dumps(messages[-40:], ensure_ascii=False)
    if agent:
        row.agent = agent
    if not row.title or row.title == "新对话":
        user_text = next((t.get("content") for t in turns if t.get("role") == "user"), "")
        if user_text:
            row.title = str(user_text).replace("\n", " ")[:40]
    row.updated_at = datetime.now()
    db.commit()
    db.refresh(row)
    return row


def history_for_ctx(row: AgentSession | None) -> list[dict]:
    if not row:
        return []
    out = []
    for item in _loads(row.messages)[-8:]:
        role = item.get("role") or "user"
        if role not in {"user", "assistant", "system"}:
            role = "user"
        out.append({"role": role, "content": item.get("content") or "", "tools": item.get("tools") or []})
    return out


def list_sessions(db: Session, user: User, limit: int = 20) -> list[AgentSession]:
    return (
        db.query(AgentSession)
        .filter_by(user_id=user.id)
        .order_by(AgentSession.id.desc())
        .limit(limit)
        .all()
    )
