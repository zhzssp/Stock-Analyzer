"""表级查询快照：P3 仅读缓存，0 次麦蕊（决策卡列仍从 DB 重算）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import settings
from src.market.normalize import Instrument
from src.query.cards import derive_card_metrics
from src.query.registry import registry

_CARD_MAP = {
    "buy_low": "buy_low",
    "buy_high": "buy_high",
    "reduce_at": "reduce_at",
    "cost": "cost",
    "vs_cost": "vs_cost",
    "dist_buy": "dist_buy",
    "dist_reduce": "dist_reduce",
    "thesis": "thesis",
    "reduce_for_rule": "reduce_for_rule",
}


def _path(user_id: int) -> Path:
    root = settings.data_dir / "snapshots"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"user_{user_id}.json"


def save_table_snapshot(
    user_id: int,
    *,
    pool: str,
    field_keys: list[str],
    codes: list[str],
    rows: list[dict],
    clock: dict | None,
    refresh_mode: str,
) -> None:
    if not rows or not field_keys:
        return
    mode = (refresh_mode or "").strip().lower()
    if mode not in ("cache", "full"):
        return
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "pool": pool,
        "field_keys": list(field_keys),
        "codes": list(codes),
        "rows": rows,
        "clock": clock or {},
        "refresh_mode": mode,
    }
    _path(user_id).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def load_table_snapshot(user_id: int) -> dict | None:
    path = _path(user_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def snapshot_meta(user_id: int) -> dict:
    snap = load_table_snapshot(user_id)
    if not snap:
        return {"has_snapshot": False}
    return {
        "has_snapshot": True,
        "saved_at": snap.get("saved_at") or "",
        "pool": snap.get("pool") or "",
        "count": len(snap.get("rows") or []),
        "field_count": len(snap.get("field_keys") or []),
        "refresh_mode": snap.get("refresh_mode") or "",
    }


def rows_from_snapshot(
    snap: dict,
    instruments: list[Instrument],
    field_keys: list[str],
    cards: dict[str, dict] | None,
) -> list[dict]:
    stored: dict[str, dict] = {}
    for raw in snap.get("rows") or []:
        if isinstance(raw, dict) and raw.get("code6"):
            stored[str(raw["code6"])] = dict(raw)
    card_keys = {s.key for s in registry.all() if s.group == "card"}
    out: list[dict] = []
    for inst in instruments:
        row = dict(
            stored.get(inst.code6)
            or {
                "code6": inst.code6,
                "code_full": inst.code_full,
                "name": inst.name,
                "market": inst.market,
                "as_of": "",
                "quote_source": "snapshot",
            }
        )
        row["code6"] = inst.code6
        row["code_full"] = inst.code_full
        row["name"] = inst.name
        row["market"] = inst.market
        if not row.get("quote_source"):
            row["quote_source"] = "snapshot"
        derived = derive_card_metrics(row.get("price"), (cards or {}).get(inst.code6), row.get("target"))
        for key in card_keys:
            if key in field_keys:
                src = _CARD_MAP.get(key)
                row[key] = derived.get(src) if src else row.get(key)
        for key in field_keys:
            row.setdefault(key, None)
        out.append(row)
    return out
