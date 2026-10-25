"""表级查询快照：P3 仅读缓存，0 次麦蕊（决策卡列仍从 DB 重算）。"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import settings
from src.market.client import _clean_concept
from src.market.normalize import Instrument
from src.platform.storage import atomic_write_text
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


# 旧文件把「自选」和「筛选一次」写在同一个 user_{id}.json 里，单只详情会把自选整表盖掉。
_WATCH_LABELS = {"watch", "自选"}


def _safe_pool(pool_id: str) -> str:
    text = (pool_id or "watch").strip() or "watch"
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in text) or "watch"


def _dir() -> Path:
    root = settings.data_dir / "snapshots"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path(user_id: int, pool_id: str) -> Path:
    return _dir() / f"user_{user_id}_{_safe_pool(pool_id)}.json"


def _legacy_path(user_id: int) -> Path:
    return _dir() / f"user_{user_id}.json"


def _read_snapshot(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _matches_pool(data: dict, pool_id: str) -> bool:
    stored = str(data.get("pool_id") or "").strip()
    if stored:
        return stored == pool_id
    label = str(data.get("pool") or "").strip()
    if pool_id == "watch":
        return label in _WATCH_LABELS
    return label == pool_id


def save_table_snapshot(
    user_id: int,
    *,
    pool: str,
    field_keys: list[str],
    codes: list[str],
    rows: list[dict],
    clock: dict | None,
    refresh_mode: str,
    pool_id: str | None = None,
) -> None:
    if not rows or not field_keys:
        return
    mode = (refresh_mode or "").strip().lower()
    if mode not in ("cache", "full"):
        return
    pid = (pool_id or pool or "watch").strip() or "watch"
    if pid == "codes":
        return
    payload = {
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "pool_id": pid,
        "pool": pool,
        "field_keys": list(field_keys),
        "codes": list(codes),
        "rows": rows,
        "clock": clock or {},
        "refresh_mode": mode,
    }
    # 快照是整表，写的时候可能正有人在读：原子替换，别让人读到半张表。
    atomic_write_text(_path(user_id, pid), json.dumps(payload, ensure_ascii=False))


def load_table_snapshot(user_id: int, pool_id: str = "watch") -> dict | None:
    pid = (pool_id or "watch").strip() or "watch"
    data = _read_snapshot(_path(user_id, pid))
    if data and _matches_pool(data, pid):
        return data
    # 升级前只有一份 user_{id}.json。池名对得上才沿用，筛选一次的旧文件不能拿来填自选。
    if pid == "watch":
        legacy = _read_snapshot(_legacy_path(user_id))
        if legacy and _matches_pool(legacy, "watch"):
            return legacy
    return None


def snapshot_meta(user_id: int, pool_id: str = "watch") -> dict:
    snap = load_table_snapshot(user_id, pool_id)
    if not snap:
        return {"has_snapshot": False}
    return {
        "has_snapshot": True,
        "saved_at": snap.get("saved_at") or "",
        "pool_id": snap.get("pool_id") or pool_id,
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
        if row.get("concept"):
            row["concept"] = _clean_concept(row["concept"])
        derived = derive_card_metrics(row.get("price"), (cards or {}).get(inst.code6), row.get("target"))
        for key in card_keys:
            if key in field_keys:
                src = _CARD_MAP.get(key)
                row[key] = derived.get(src) if src else row.get(key)
        for key in field_keys:
            row.setdefault(key, None)
        out.append(row)
    return out
