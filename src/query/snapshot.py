"""表级查询快照：P3 仅读缓存，0 次麦蕊（决策卡列仍从 DB 重算）。

整池查完会写成一份完整快照。沪市、深市这类大池一次只查一页、或中途停下时，
已经组装完的行并进同一份未完成快照，不把没查到的股票删掉。
按快照显示时，若有更晚且盖住当前这批的完整快照，或未完成大池里已有的股票，
就抽出这些更新的行；空格子仍留原来的值。

查询和全量更新还会按上海日历日期另存一份，给日期框打开。
当前这份 user_{id}_{pool}.json 仍是实时表，按日副本不写回它，刷新行情也不另存。
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import settings
from src.market.client import _clean_concept
from src.market.clock import SHANGHAI
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
_write_lock = threading.Lock()


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


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shanghai_day(stamp: str) -> str:
    text = (stamp or "").strip()
    now = datetime.now(SHANGHAI)
    if not text:
        return now.date().isoformat()
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return now.date().isoformat()
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(SHANGHAI).date().isoformat()


def _normalize_day(text: str) -> str | None:
    raw = (text or "").strip()
    if len(raw) == 8 and raw.isdigit():
        raw = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"
    try:
        datetime.strptime(raw, "%Y-%m-%d")
    except ValueError:
        return None
    return raw


def _user_days_dir(user_id: int) -> Path:
    return _dir() / "days" / f"user_{user_id}"


def _day_file(user_id: int, day: str, pool_id: str) -> Path:
    return _user_days_dir(user_id) / day / f"{_safe_pool(pool_id)}.json"


def _index_path(user_id: int) -> Path:
    return _user_days_dir(user_id) / "index.json"


def _load_index(user_id: int) -> list[dict]:
    data = _read_snapshot(_index_path(user_id)) or {}
    entries = data.get("entries") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        return []
    return [dict(item) for item in entries if isinstance(item, dict)]


def _save_index(user_id: int, entries: list[dict]) -> None:
    path = _index_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps({"entries": entries}, ensure_ascii=False))


def _entry_key(entry: dict) -> tuple[str, str]:
    return (str(entry.get("date") or ""), str(entry.get("pool_id") or ""))


def _index_row(payload: dict, day: str, last_used: str) -> dict:
    rows = payload.get("rows") or []
    return {
        "date": day,
        "pool_id": str(payload.get("pool_id") or ""),
        "pool": str(payload.get("pool") or ""),
        "saved_at": str(payload.get("saved_at") or ""),
        "last_used": last_used,
        "complete": bool(payload.get("complete")),
        "covered": int(payload.get("covered") or len(rows)),
        "total": int(payload.get("total") or len(rows)),
    }


def _drop_day_file(user_id: int, day: str, pool_id: str) -> None:
    path = _day_file(user_id, day, pool_id)
    try:
        path.unlink()
    except OSError:
        pass
    try:
        path.parent.rmdir()
    except OSError:
        pass


def _keep_limit() -> int:
    return max(int(getattr(settings, "snapshot_day_keep", 30) or 30), 1)


def _evict_days_locked(user_id: int, entries: list[dict], protected: tuple[str, str]) -> list[dict]:
    """只在名册新增加一条、并且超过上限时丢掉最久没打开的。刚写入的那条不参与。"""
    keep = _keep_limit()
    while len(entries) > keep:
        victims = [item for item in entries if _entry_key(item) != protected]
        if not victims:
            break
        victim = min(
            victims,
            key=lambda item: (str(item.get("last_used") or ""), str(item.get("saved_at") or "")),
        )
        _drop_day_file(user_id, str(victim.get("date") or ""), str(victim.get("pool_id") or ""))
        gone = _entry_key(victim)
        entries = [item for item in entries if _entry_key(item) != gone]
    return entries


def _archive_day_locked(user_id: int, payload: dict) -> None:
    """调用方已持有写锁。按上海日期另存，同一天同一池覆盖，不另占名额。"""
    day = _shanghai_day(str(payload.get("saved_at") or ""))
    pid = str(payload.get("pool_id") or "")
    if not day or not pid:
        return
    path = _day_file(user_id, day, pid)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(payload, ensure_ascii=False))
    now = _stamp()
    key = (day, pid)
    entries = _load_index(user_id)
    row = _index_row(payload, day, now)
    found = False
    for idx, entry in enumerate(entries):
        if _entry_key(entry) == key:
            entries[idx] = row
            found = True
            break
    if not found:
        entries.append(row)
        entries = _evict_days_locked(user_id, entries, key)
    _save_index(user_id, entries)


def _touch_day_locked(user_id: int, day: str, pool_id: str) -> None:
    key = (day, pool_id)
    entries = _load_index(user_id)
    now = _stamp()
    changed = False
    for entry in entries:
        if _entry_key(entry) == key:
            entry["last_used"] = now
            changed = True
            break
    if changed:
        _save_index(user_id, entries)


def load_day_for_view(user_id: int, day: str) -> dict | None:
    """打开某一天要显示的那份：优先最晚的完整表，没有完整表再用最晚的未完成表。

    打开成功会把这份的 last_used 拨到现在，使它在淘汰时排到最后。不改实时表。
    """
    norm = _normalize_day(day)
    if not norm:
        return None
    with _write_lock:
        entries = [item for item in _load_index(user_id) if str(item.get("date") or "") == norm]
        ranked = sorted(entries, key=lambda item: str(item.get("saved_at") or ""), reverse=True)
        complete = [item for item in ranked if item.get("complete")]
        rest = [item for item in ranked if not item.get("complete")]
        for entry in complete + rest:
            pid = str(entry.get("pool_id") or "")
            data = _read_snapshot(_day_file(user_id, norm, pid))
            if not data:
                continue
            _touch_day_locked(user_id, norm, pid)
            return data
    return None


def _filled(value: Any) -> bool:
    return value is not None and value != "" and value != "—"


def _row_time(snap: dict, row: dict) -> str:
    return str(row.get("row_saved_at") or snap.get("saved_at") or "")


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
    saved_at: str | None = None,
) -> None:
    if not rows or not field_keys:
        return
    mode = (refresh_mode or "").strip().lower()
    if mode not in ("cache", "full"):
        return
    pid = (pool_id or pool or "watch").strip() or "watch"
    if pid == "codes":
        return
    stamp = saved_at or _stamp()
    stored = []
    for raw in rows:
        if not isinstance(raw, dict) or not raw.get("code6"):
            continue
        row = dict(raw)
        row["row_saved_at"] = stamp
        stored.append(row)
    if not stored:
        return
    payload = {
        "saved_at": stamp,
        "pool_id": pid,
        "pool": pool,
        "complete": True,
        "field_keys": list(field_keys),
        "codes": list(codes),
        "rows": stored,
        "covered": len(stored),
        "total": len(stored),
        "clock": clock or {},
        "refresh_mode": mode,
    }
    # 快照是整表，写的时候可能正有人在读：原子替换，别让人读到半张表。
    # 同一把锁里再按上海日期留一份，供日期框打开。实时文件仍被这次结果覆盖。
    with _write_lock:
        atomic_write_text(_path(user_id, pid), json.dumps(payload, ensure_ascii=False))
        _archive_day_locked(user_id, payload)


def merge_partial_snapshot(
    user_id: int,
    *,
    pool: str,
    field_keys: list[str],
    rows: list[dict],
    clock: dict | None,
    refresh_mode: str,
    pool_id: str,
    total: int = 0,
    saved_at: str | None = None,
) -> None:
    """把已经组装完的一页并进该池快照。没出现在这页里的股票保留。"""
    mode = (refresh_mode or "").strip().lower()
    if mode not in ("cache", "full"):
        return
    pid = (pool_id or "").strip()
    if not pid or pid == "codes" or not rows or not field_keys:
        return
    stamp = saved_at or _stamp()
    with _write_lock:
        current = _read_snapshot(_path(user_id, pid)) or {}
        if current and not _matches_pool(current, pid):
            current = {}
        by_code: dict[str, dict] = {}
        prev_stamp = str(current.get("saved_at") or "")
        for raw in current.get("rows") or []:
            if isinstance(raw, dict) and raw.get("code6"):
                kept = dict(raw)
                # 这页没刷新到的行，时间停在原来那次，不能跟着文件时间一起变新。
                if not kept.get("row_saved_at") and prev_stamp:
                    kept["row_saved_at"] = prev_stamp
                by_code[str(raw["code6"])] = kept
        for raw in rows:
            if not isinstance(raw, dict) or not raw.get("code6"):
                continue
            code = str(raw["code6"])
            old = by_code.get(code)
            if old and _row_time(current, old) > stamp:
                continue
            merged = dict(old or {})
            for key in field_keys:
                if key in raw and _filled(raw.get(key)):
                    merged[key] = raw.get(key)
            for key in ("code6", "code_full", "name", "market", "as_of", "quote_source"):
                if _filled(raw.get(key)):
                    merged[key] = raw.get(key)
            merged["code6"] = code
            merged["row_saved_at"] = stamp
            by_code[code] = merged
        if not by_code:
            return
        fields = list(dict.fromkeys([*(current.get("field_keys") or []), *field_keys]))
        complete = bool(current.get("complete"))
        pool_total = int(total or current.get("total") or 0)
        if pool_total and len(by_code) >= pool_total:
            complete = True
        payload = {
            "saved_at": stamp,
            "pool_id": pid,
            "pool": pool or current.get("pool") or pid,
            "complete": complete,
            "field_keys": fields,
            "codes": [by_code[c].get("code_full") or c for c in by_code],
            "rows": list(by_code.values()),
            "covered": len(by_code),
            "total": pool_total or len(by_code),
            "clock": clock or current.get("clock") or {},
            "refresh_mode": mode,
        }
        atomic_write_text(_path(user_id, pid), json.dumps(payload, ensure_ascii=False))
        _archive_day_locked(user_id, payload)


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
        "complete": bool(snap.get("complete", True)),
        "covered": int(snap.get("covered") or len(snap.get("rows") or [])),
    }


def _iter_snapshots(user_id: int) -> list[dict]:
    out: list[dict] = []
    prefix = f"user_{user_id}_"
    root = _dir()
    if not root.exists():
        return out
    for path in root.glob(f"{prefix}*.json"):
        data = _read_snapshot(path)
        if not data or not data.get("pool_id"):
            continue
        if "complete" not in data:
            data["complete"] = True
        out.append(data)
    return out


def _overlay(base: dict, newer: dict) -> dict:
    """新行里有值的格子盖上去，空格子留旧值。"""
    out = dict(base)
    for key, value in newer.items():
        if key in {"row_saved_at"}:
            continue
        if _filled(value):
            out[key] = value
    if newer.get("row_saved_at"):
        out["row_saved_at"] = newer.get("row_saved_at")
    return out


def compose_snapshot(
    user_id: int,
    pool_id: str,
    instruments: list[Instrument],
) -> dict | None:
    """为当前这批股票挑最新来源。

    完整快照必须盖住整批，且晚于这一池自己的快照，才整批采用。
    未完成的大池只贡献它已经查到、并且更晚的那些股票。
    """
    pid = (pool_id or "watch").strip() or "watch"
    own = load_table_snapshot(user_id, pid)
    requested = [inst.code6 for inst in instruments]
    req_set = set(requested)
    if not req_set:
        return None
    own_rows = {}
    if own:
        for raw in own.get("rows") or []:
            if isinstance(raw, dict) and raw.get("code6"):
                own_rows[str(raw["code6"])] = dict(raw)
    own_at = str((own or {}).get("saved_at") or "")

    complete_donors: list[dict] = []
    partial_best: dict[str, tuple[str, dict, dict]] = {}
    for snap in _iter_snapshots(user_id):
        if str(snap.get("pool_id") or "") == pid:
            continue
        rows = {}
        for raw in snap.get("rows") or []:
            if isinstance(raw, dict) and raw.get("code6"):
                rows[str(raw["code6"])] = raw
        if not rows:
            continue
        if snap.get("complete", True):
            if req_set <= set(rows):
                complete_donors.append(snap)
            continue
        for code, row in rows.items():
            if code not in req_set:
                continue
            when = _row_time(snap, row)
            prev = partial_best.get(code)
            if prev is None or when > prev[0]:
                partial_best[code] = (when, row, snap)

    best_complete = max(complete_donors, key=lambda s: str(s.get("saved_at") or ""), default=None)
    complete_rows = {}
    if best_complete:
        for raw in best_complete.get("rows") or []:
            if isinstance(raw, dict) and raw.get("code6"):
                complete_rows[str(raw["code6"])] = raw

    chosen: dict[str, dict] = {}
    origin: dict[str, dict | None] = {}
    for code in requested:
        base = dict(own_rows.get(code) or {})
        base_at = _row_time(own, base) if own and base else ""
        row = base
        src = None
        if code in complete_rows:
            donor_at = _row_time(best_complete, complete_rows[code])
            if donor_at > (base_at or ""):
                row = _overlay(base, complete_rows[code])
                row["row_saved_at"] = donor_at
                src = best_complete
                base_at = donor_at
        partial = partial_best.get(code)
        if partial and partial[0] > (base_at or ""):
            row = _overlay(row, partial[1])
            row["row_saved_at"] = partial[0]
            src = partial[2]
        if row:
            chosen[code] = row
            origin[code] = src

    if own is None and not any(origin.get(code) for code in requested):
        return None

    sources: dict[str, dict] = {}
    own_used = 0
    for code in requested:
        src = origin.get(code)
        if src is None:
            if code in own_rows:
                own_used += 1
            continue
        key = str(src.get("pool_id") or "")
        bucket = sources.get(key)
        if bucket is None:
            bucket = {
                "pool_id": key,
                "pool": src.get("pool") or key,
                "saved_at": src.get("saved_at") or "",
                "complete": bool(src.get("complete", True)),
                "covered": int(src.get("covered") or len(src.get("rows") or [])),
                "used": 0,
            }
            sources[key] = bucket
        bucket["used"] += 1
        row_at = _row_time(src, chosen.get(code) or {})
        if row_at and row_at > str(bucket.get("saved_at") or ""):
            bucket["saved_at"] = row_at

    used_complete = best_complete if any(
        src is best_complete for src in origin.values()
    ) else None
    return {
        "saved_at": (used_complete or own or {}).get("saved_at") or "",
        "pool_id": pid,
        "pool": (own or {}).get("pool") or pid,
        "complete": bool((own or {}).get("complete", True)) if own else False,
        "field_keys": list((own or used_complete or {}).get("field_keys") or []),
        "rows": [chosen.get(code) or {"code6": code} for code in requested],
        "clock": (used_complete or own or {}).get("clock") or {},
        "refresh_mode": (own or {}).get("refresh_mode") or "",
        "sources": list(sources.values()),
        "own_saved_at": own_at,
        "own_pool": (own or {}).get("pool") or "",
        "own_used": own_used,
        "row_count": len(requested),
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
