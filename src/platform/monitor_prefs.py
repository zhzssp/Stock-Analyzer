from __future__ import annotations

import json

from sqlalchemy.orm import Session

from src.market.institutions import INSTITUTIONS
from src.models import MonitorPref, User
from src.platform.web_sources import enabled_kinds, normalize_sources


def default_selected() -> list[str]:
    return [i["name"] for i in INSTITUTIONS]


def _empty() -> dict:
    return {"selected": default_selected(), "custom": [], "sources": []}


def parse_pref(pref: MonitorPref | None) -> dict:
    if not pref or not pref.institutions:
        return _empty()
    try:
        data = json.loads(pref.institutions)
    except json.JSONDecodeError:
        return _empty()
    if not isinstance(data, dict):
        return _empty()
    selected = data.get("selected")
    if not isinstance(selected, list):
        selected = default_selected()
    custom = data.get("custom") if isinstance(data.get("custom"), list) else []
    try:
        sources = normalize_sources(data.get("sources") if isinstance(data.get("sources"), list) else [], strict=False)
    except ValueError:
        sources = []
    return {"selected": [str(x) for x in selected if str(x).strip()], "custom": custom, "sources": sources}


def institution_catalog_for(db: Session, user_id: int) -> list[dict]:
    pref = db.query(MonitorPref).filter_by(user_id=user_id).first()
    parsed = parse_pref(pref)
    selected = set(parsed["selected"])
    out = [i for i in INSTITUTIONS if i["name"] in selected]
    for raw in parsed["custom"]:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        aliases = tuple(a for a in (raw.get("aliases") or []) if str(a).strip())
        out.append({"kind": raw.get("kind") or "custom", "name": name, "aliases": (name, *aliases)})
    return out


def sources_for(db: Session, user_id: int) -> list[dict]:
    pref = db.query(MonitorPref).filter_by(user_id=user_id).first()
    return parse_pref(pref)["sources"]


def source_kinds_for(db: Session, user_id: int) -> set[str]:
    return enabled_kinds(sources_for(db, user_id))


def save_pref(
    db: Session,
    user: User,
    *,
    selected: list[str] | None = None,
    custom: list | None = None,
    sources: list | None = None,
) -> MonitorPref:
    pref = db.query(MonitorPref).filter_by(user_id=user.id).first()
    parsed = parse_pref(pref)
    if selected is not None:
        parsed["selected"] = [str(x) for x in selected if str(x).strip()]
    if custom is not None:
        parsed["custom"] = custom
    if sources is not None:
        parsed["sources"] = normalize_sources(sources)
    payload = json.dumps(
        {"selected": parsed["selected"], "custom": parsed["custom"], "sources": parsed["sources"]},
        ensure_ascii=False,
    )
    if pref:
        pref.institutions = payload
    else:
        pref = MonitorPref(user_id=user.id, institutions=payload)
        db.add(pref)
    db.commit()
    db.refresh(pref)
    return pref


def pref_payload(pref: MonitorPref | None) -> dict:
    parsed = parse_pref(pref)
    return {
        "selected": parsed["selected"],
        "custom": parsed["custom"],
        "sources": parsed["sources"],
        "catalog": [
            {"kind": i["kind"], "name": i["name"], "aliases": list(i["aliases"])}
            for i in INSTITUTIONS
        ],
    }
