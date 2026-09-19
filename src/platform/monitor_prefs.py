from __future__ import annotations

import json

from sqlalchemy.orm import Session

from src.market.institutions import INSTITUTIONS
from src.models import MonitorPref


def default_selected() -> list[str]:
    return [i["name"] for i in INSTITUTIONS]


def parse_pref(pref: MonitorPref | None) -> dict:
    if not pref or not pref.institutions:
        return {"selected": default_selected(), "custom": []}
    try:
        data = json.loads(pref.institutions)
    except json.JSONDecodeError:
        return {"selected": default_selected(), "custom": []}
    if not isinstance(data, dict):
        return {"selected": default_selected(), "custom": []}
    selected = data.get("selected")
    if not isinstance(selected, list):
        selected = default_selected()
    custom = data.get("custom") if isinstance(data.get("custom"), list) else []
    return {"selected": [str(x) for x in selected if str(x).strip()], "custom": custom}


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


def pref_payload(pref: MonitorPref | None) -> dict:
    parsed = parse_pref(pref)
    return {
        "selected": parsed["selected"],
        "custom": parsed["custom"],
        "catalog": [
            {"kind": i["kind"], "name": i["name"], "aliases": list(i["aliases"])}
            for i in INSTITUTIONS
        ],
    }
