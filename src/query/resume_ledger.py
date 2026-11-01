"""刷新行情 / 全量更新的断点账本。和表快照、五分钟墙钟档分开存放。

一只股票的现价按批写入，慢字段按只写入。名单顺序变了就整本作废；列变了只补还没取的块。
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from src.config import settings
from src.platform.storage import atomic_write_text
from src.query import resume_window as window

QUOTE_KEYS = (
    "price",
    "pct",
    "pe",
    "pb",
    "turnover",
    "mcap",
    "fcap",
    "pct60",
    "pct_ytd",
    "vs_cost",
    "dist_buy",
    "dist_reduce",
    "as_of",
    "quote_source",
)
# 离底跟着现价走。现价作废时先拿掉，若日线底还在，拼行时再用新价重算。
QUOTE_STRIP = QUOTE_KEYS + ("off_low",)
BLOCK_KEYS = {
    "quote": QUOTE_KEYS,
    "profile": ("industry", "sector", "sw_l1", "hot_concepts", "concept", "business"),
    "holders": ("holders", "top_holders"),
    "finance": ("zgb", "ltgb", "mgwfplr", "yffy", "mgjzc", "eps", "gross", "net"),
    "flow": ("flow_in", "flow_out", "flow_net"),
    "indicators": ("pct3", "pct5", "pct10"),
    "bars": ("low1y", "low_long", "high", "off_low", "multiple", "target", "low_note"),
}
SLOW_KINDS = ("profile", "holders", "finance", "flow", "indicators", "bars")
_QUOTE_FROM_RAW = (
    ("p", "price"),
    ("pc", "pct"),
    ("pe", "pe"),
    ("sjl", "pb"),
    ("hs", "turnover"),
    ("sz", "mcap"),
    ("lt", "fcap"),
    ("zdf60", "pct60"),
    ("zdfnc", "pct_ytd"),
    ("as_of", "as_of"),
    ("source", "quote_source"),
)
_SAFE_POOL = re.compile(r"[^A-Za-z0-9_.-]+")
_LOCKS: dict[str, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()
PAGE_SIZE = 100


def ledger_dir() -> Path:
    return settings.data_dir / "resume"


def _lock_for(path: Path) -> threading.RLock:
    key = str(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


def _safe_pool(pool_id: str) -> str:
    return _SAFE_POOL.sub("_", str(pool_id or "")).strip("._") or "pool"


def ledger_path(user_id: int, pool_id: str, mode: str, root: Path | None = None) -> Path:
    name = "quote.json" if mode == "quote" else "full.json"
    return (root or ledger_dir()) / f"user_{int(user_id)}" / _safe_pool(pool_id) / name


def _filled(value: Any) -> bool:
    return value not in (None, "")


def _parse(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        return window.shanghai(datetime.fromisoformat(text))
    except ValueError:
        return None


def _stamp(moment: datetime | None = None) -> str:
    return window.shanghai(moment or window.now_shanghai()).isoformat()


def required_work(field_keys: list[str] | None, mode: str) -> set[str]:
    from src.query.engine import fetch_need
    from src.query.registry import registry

    keys = list(field_keys) if field_keys else registry.default_keys()
    specs = []
    for key in keys:
        try:
            specs.append(registry.get(key))
        except KeyError:
            continue
    if not specs:
        return set()
    column_need = {dep for spec in specs for dep in spec.requires}
    if any(spec.group == "card" for spec in specs):
        column_need.add("quote")
    return set(fetch_need(column_need, mode))


def fresh_ledger(order: list[str], field_keys: list[str], mode: str) -> dict:
    return {
        "status": "open",
        "mode": mode,
        "field_keys": list(field_keys),
        "order": [str(code) for code in order],
        "quote_oldest": "",
        "quotes": {},
        "blocks": {},
        "rows": {},
    }


def _normalize(data: dict) -> dict:
    data.setdefault("status", "open")
    data.setdefault("mode", "full")
    data.setdefault("field_keys", [])
    data.setdefault("order", [])
    data.setdefault("quote_oldest", "")
    if not isinstance(data.get("quotes"), dict):
        data["quotes"] = {}
    if not isinstance(data.get("blocks"), dict):
        data["blocks"] = {}
    if not isinstance(data.get("rows"), dict):
        data["rows"] = {}
    data["order"] = [str(code) for code in data.get("order") or []]
    return data


def load_ledger(path: Path) -> dict | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    return _normalize(raw)


def save_ledger(path: Path, ledger: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path, json.dumps(ledger, ensure_ascii=False))


def _price_of(payload: dict) -> Any:
    if payload.get("p") not in (None, ""):
        return payload.get("p")
    if payload.get("price") not in (None, ""):
        return payload.get("price")
    return None


def _apply_quote_payload(row: dict, payload: dict) -> None:
    if any(key in payload for key, _name in _QUOTE_FROM_RAW):
        for src, dest in _QUOTE_FROM_RAW:
            if _filled(payload.get(src)):
                row[dest] = payload.get(src)
        return
    for key in QUOTE_KEYS:
        if _filled(payload.get(key)):
            row[key] = payload.get(key)


def _seed_from_row(row: dict) -> dict:
    if not _filled(row.get("price")):
        return {}
    return {
        "p": row.get("price"),
        "pc": row.get("pct"),
        "pe": row.get("pe"),
        "sjl": row.get("pb"),
        "hs": row.get("turnover"),
        "sz": row.get("mcap"),
        "lt": row.get("fcap"),
        "zdf60": row.get("pct60"),
        "zdfnc": row.get("pct_ytd"),
        "as_of": row.get("as_of") or "",
        "source": row.get("quote_source") or "resume",
    }


def _recompute_off_low(row: dict) -> None:
    if _filled(row.get("off_low")):
        return
    if not _filled(row.get("price")) or not _filled(row.get("low_long")):
        return
    try:
        price = float(row["price"])
        low = float(row["low_long"])
    except (TypeError, ValueError):
        return
    if not low:
        return
    row["off_low"] = round((price - low) / low * 100, 2)


def merge_filled(base: dict, fresh: dict, keys: tuple[str, ...] | list[str]) -> None:
    for key in keys:
        if _filled(fresh.get(key)):
            base[key] = fresh.get(key)


def overlay_row(base: dict | None, fresh: dict, blocks: set[str]) -> dict:
    row = dict(base or {})
    if not row:
        row = dict(fresh)
        if "quote" in blocks:
            _recompute_off_low(row)
        return row
    for kind in blocks:
        merge_filled(row, fresh, BLOCK_KEYS.get(kind, ()))
    for key in ("code6", "code_full", "code", "name", "market"):
        if _filled(fresh.get(key)):
            row[key] = fresh.get(key)
    if "quote" in blocks:
        _recompute_off_low(row)
    return row


def _quote_anchor(ledger: dict) -> datetime | None:
    oldest = _parse(ledger.get("quote_oldest"))
    if oldest is not None:
        return oldest
    stamps = [_parse(value) for value in (ledger.get("quotes") or {}).values()]
    stamps = [item for item in stamps if item is not None]
    return min(stamps) if stamps else None


def _quote_ok(ledger: dict, code: str, now: datetime, is_trading) -> bool:
    stamp = _parse((ledger.get("quotes") or {}).get(code))
    oldest = _quote_anchor(ledger)
    if stamp is None or oldest is None:
        return False
    return window.quote_reusable(stamp, now, oldest, is_trading)


def _block_ok(ledger: dict, code: str, kind: str, now: datetime, is_trading) -> bool:
    stamp = _parse(((ledger.get("blocks") or {}).get(code) or {}).get(kind))
    if stamp is None:
        return False
    return window.block_reusable(kind, stamp, now, is_trading)


def expire_ledger(ledger: dict, now: datetime, is_trading) -> str:
    """按当前时间丢掉过期的现价和慢字段。返回给用户看的原因，没有过期则是空字符串。"""
    quotes = dict(ledger.get("quotes") or {})
    oldest = _quote_anchor(ledger)
    kept: dict[str, str] = {}
    partial = ""
    all_drop = ""
    if quotes and oldest is not None:
        same_phase: dict[str, str] = {}
        for code, raw in quotes.items():
            stamp = _parse(raw)
            if stamp is None:
                continue
            if window.phase_at(stamp, is_trading) != window.phase_at(now, is_trading):
                if not partial:
                    partial = window.partial_quote_reason(stamp, now, is_trading)
                continue
            if window.phase_at(now, is_trading) in window.NEVER_RESUME:
                if not all_drop:
                    all_drop = "集合竞价期间不续传现价"
                continue
            same_phase[code] = raw
        if same_phase:
            stamps = [_parse(raw) for raw in same_phase.values()]
            anchor = min(item for item in stamps if item is not None)
            if window.shanghai(now) - anchor > window.QUOTE_WINDOW:
                all_drop = all_drop or "现价已过 90 分钟，现价重取"
            else:
                kept = same_phase
                ledger["quote_oldest"] = anchor.isoformat()
        elif oldest is not None and not all_drop:
            all_drop = window.quote_drop_reason(oldest, now, is_trading) or partial
    lost = set(quotes) - set(kept)
    ledger["quotes"] = kept
    if not kept:
        ledger["quote_oldest"] = ""
    for code in lost:
        row = (ledger.get("rows") or {}).get(code)
        if isinstance(row, dict):
            for key in QUOTE_STRIP:
                row.pop(key, None)

    kept_slow: set[str] = set()
    for code, blocks in list((ledger.get("blocks") or {}).items()):
        if not isinstance(blocks, dict):
            ledger["blocks"][code] = {}
            continue
        for kind in list(blocks.keys()):
            if kind not in SLOW_KINDS or not _block_ok(ledger, code, kind, now, is_trading):
                blocks.pop(kind, None)
                row = (ledger.get("rows") or {}).get(code)
                if isinstance(row, dict):
                    for key in BLOCK_KEYS.get(kind, ()):
                        row.pop(key, None)
            else:
                kept_slow.add(kind)
    if not kept and (all_drop or partial):
        reason = all_drop or partial
        phrase = window.slow_phrase(kept_slow)
        if phrase:
            reason = f"{reason}，{phrase}接着补"
        return reason
    if kept and partial and len(kept) < len(quotes):
        return partial
    return ""


def _slow_left(ledger: dict, required: set[str], now: datetime, is_trading) -> bool:
    needed = {kind for kind in required if kind in SLOW_KINDS}
    if not needed:
        return False
    for code in ledger.get("order") or []:
        for kind in needed:
            if not _block_ok(ledger, code, kind, now, is_trading):
                return True
    return False


def _quoted_count(ledger: dict, now: datetime, is_trading) -> int:
    return sum(1 for code in ledger.get("order") or [] if _quote_ok(ledger, code, now, is_trading))


def code_done(ledger: dict, code: str, required: set[str], now: datetime, is_trading) -> bool:
    if "quote" in required and not _quote_ok(ledger, code, now, is_trading):
        return False
    for kind in required:
        if kind == "quote":
            continue
        if not _block_ok(ledger, code, kind, now, is_trading):
            return False
    return True


def mark_complete(ledger: dict, required: set[str], now: datetime, is_trading) -> bool:
    order = ledger.get("order") or []
    if not order or not required:
        return False
    if all(code_done(ledger, code, required, now, is_trading) for code in order):
        ledger["status"] = "complete"
        return True
    ledger["status"] = "open"
    return False


@dataclass
class PagePlan:
    todo: list = field(default_factory=list)
    skip: dict[str, set[str]] = field(default_factory=dict)
    seed: dict[str, dict] = field(default_factory=dict)
    refetched: dict[str, set[str]] = field(default_factory=dict)
    kept: dict[str, dict] = field(default_factory=dict)
    skipped: int = 0
    refetch_count: int = 0


class ResumeSession:
    def __init__(self, path: Path, ledger: dict, required: set[str], is_trading, resumed: bool, reason: str):
        self.path = path
        self.ledger = ledger
        self.required = required
        self.is_trading = is_trading
        self.resumed = resumed
        self.reason = reason
        self.plan = PagePlan()
        self._insts: dict[str, Any] = {}

    @classmethod
    def open(
        cls,
        *,
        user_id: int,
        pool_id: str,
        mode: str,
        order: list[str],
        field_keys: list[str],
        is_trading: Callable | None = None,
        root: Path | None = None,
        now: datetime | None = None,
    ) -> ResumeSession | None:
        mode = (mode or "").strip().lower()
        if mode not in ("quote", "full") or pool_id == "codes":
            return None
        required = required_work(field_keys, mode)
        if not required:
            return None
        trading = is_trading or window.weekday_trading
        moment = window.shanghai(now or window.now_shanghai())
        path = ledger_path(user_id, pool_id, mode, root)
        lock = _lock_for(path)
        with lock:
            loaded = load_ledger(path)
            resumed = False
            reset = ""
            if loaded is None:
                ledger = fresh_ledger(order, field_keys, mode)
            elif loaded.get("status") == "complete":
                ledger = fresh_ledger(order, field_keys, mode)
                reset = "上一轮已经完成，重新开始"
            elif list(loaded.get("order") or []) != [str(code) for code in order]:
                ledger = fresh_ledger(order, field_keys, mode)
                reset = "名单变了，重新开始"
            else:
                ledger = loaded
                resumed = True
            ledger["field_keys"] = list(field_keys)
            ledger["mode"] = mode
            drop = ""
            if resumed:
                drop = expire_ledger(ledger, moment, trading)
                mark_complete(ledger, required, moment, trading)
                if ledger.get("status") == "complete":
                    ledger = fresh_ledger(order, field_keys, mode)
                    resumed = False
                    reset = "上一轮已经完成，重新开始"
                    drop = ""
                else:
                    save_ledger(path, ledger)
            quoted = _quoted_count(ledger, moment, trading) if resumed else 0
            slow_left = _slow_left(ledger, required, moment, trading) if resumed else False
            if drop:
                reason = drop
            elif reset:
                reason = reset
            elif resumed:
                reason = window.resume_banner(window.phase_at(moment, trading), quoted, len(order), slow_left)
            else:
                reason = ""
            return cls(path, ledger, required, trading, resumed, reason)

    def plan_page(self, insts: list) -> PagePlan:
        moment = window.now_shanghai()
        plan = PagePlan()
        self._insts = {}
        for inst in insts:
            code = str(inst.code6)
            self._insts[code] = inst
            row = (self.ledger.get("rows") or {}).get(code)
            if isinstance(row, dict):
                plan.kept[code] = dict(row)
            missing = set()
            if "quote" in self.required and not _quote_ok(self.ledger, code, moment, self.is_trading):
                missing.add("quote")
            for kind in self.required:
                if kind == "quote":
                    continue
                if not _block_ok(self.ledger, code, kind, moment, self.is_trading):
                    missing.add(kind)
            if not missing:
                plan.skipped += 1
                continue
            plan.todo.append(inst)
            plan.refetched[code] = set(missing)
            plan.skip[code] = set(self.required - missing)
            plan.refetch_count += 1
            if "quote" in plan.skip[code] and code in plan.kept:
                seed = _seed_from_row(plan.kept[code])
                if seed:
                    plan.seed[code] = seed
        self.plan = plan
        return plan

    def blocks_for(self, code: str) -> set[str]:
        return set(self.plan.refetched.get(str(code or ""), set()))

    def overlay(self, fresh: dict) -> dict:
        code = str(fresh.get("code6") or "")
        return overlay_row(self.plan.kept.get(code), fresh, self.blocks_for(code))

    def _touch_identity(self, code: str, row: dict) -> None:
        inst = self._insts.get(code)
        if inst is None:
            return
        row.setdefault("code6", code)
        if _filled(getattr(inst, "code_full", None)):
            row.setdefault("code_full", inst.code_full)
            row.setdefault("code", inst.code_full)
        if _filled(getattr(inst, "name", None)):
            row.setdefault("name", inst.name)
        if _filled(getattr(inst, "market", None)):
            row.setdefault("market", inst.market)

    def note_quotes(self, quotes: dict) -> None:
        if not quotes:
            return
        moment = _stamp()
        lock = _lock_for(self.path)
        with lock:
            changed = False
            for code, payload in quotes.items():
                if not isinstance(payload, dict):
                    continue
                key = str(code)
                if _price_of(payload) is None:
                    continue
                if key not in (self.ledger.get("quotes") or {}):
                    self.ledger["quotes"][key] = moment
                    changed = True
                if not self.ledger.get("quote_oldest"):
                    self.ledger["quote_oldest"] = self.ledger["quotes"][key]
                row = dict((self.ledger.get("rows") or {}).get(key) or {})
                _apply_quote_payload(row, payload)
                self._touch_identity(key, row)
                row["code6"] = key
                self.ledger["rows"][key] = row
                changed = True
            if changed:
                self._save()

    def note_row(self, row: dict, blocks: set[str]) -> None:
        code = str(row.get("code6") or "")
        if not code:
            return
        moment = _stamp()
        lock = _lock_for(self.path)
        with lock:
            stored = dict((self.ledger.get("rows") or {}).get(code) or {})
            if blocks:
                for kind in blocks:
                    merge_filled(stored, row, BLOCK_KEYS.get(kind, ()))
            else:
                stored = overlay_row(stored, row, set(self.required))
            if _filled(row.get("off_low")) and ("quote" in blocks or "bars" in blocks):
                stored["off_low"] = row.get("off_low")
            for key in ("code6", "code_full", "code", "name", "market"):
                if _filled(row.get(key)):
                    stored[key] = row.get(key)
            self._touch_identity(code, stored)
            stored["code6"] = code
            self.ledger["rows"][code] = stored
            have = dict((self.ledger.get("blocks") or {}).get(code) or {})
            for kind in blocks:
                if kind == "quote":
                    if _filled(stored.get("price")) and code not in (self.ledger.get("quotes") or {}):
                        self.ledger["quotes"][code] = moment
                        if not self.ledger.get("quote_oldest"):
                            self.ledger["quote_oldest"] = moment
                    continue
                if kind in SLOW_KINDS and kind not in have:
                    have[kind] = moment
            self.ledger["blocks"][code] = have
            self._save()

    def stitch(self, insts: list, fresh_rows: list[dict]) -> list[dict]:
        fresh = {str(row.get("code6")): row for row in fresh_rows if isinstance(row, dict) and row.get("code6")}
        out = []
        for inst in insts:
            code = str(inst.code6)
            neu = fresh.get(code)
            base = self.plan.kept.get(code)
            if neu is None:
                if base:
                    out.append(dict(base))
                continue
            out.append(overlay_row(base, neu, self.blocks_for(code)))
        return out

    def close(self) -> None:
        lock = _lock_for(self.path)
        with lock:
            mark_complete(self.ledger, self.required, window.now_shanghai(), self.is_trading)
            self._save()

    def public(self) -> dict:
        return {
            "used": bool(self.resumed),
            "skipped": int(self.plan.skipped),
            "refetched": int(self.plan.refetch_count),
            "reason": self.reason or "",
        }

    def _save(self) -> None:
        try:
            save_ledger(self.path, self.ledger)
        except OSError:
            return


def peek_resume(
    *,
    user_id: int,
    pool_id: str,
    mode: str,
    order: list[str],
    field_keys: list[str],
    page_size: int = PAGE_SIZE,
    is_trading: Callable | None = None,
    root: Path | None = None,
    now: datetime | None = None,
) -> dict:
    mode = "quote" if (mode or "").strip().lower() == "quote" else "full"
    trading = is_trading or window.weekday_trading
    moment = window.shanghai(now or window.now_shanghai())
    page = max(1, min(int(page_size or PAGE_SIZE), 500))
    codes = [str(code) for code in order]
    empty = {
        "status": "none",
        "reason": "",
        "total": len(codes),
        "order": codes,
        "pages": [],
        "resume_from": 0,
        "quoted": 0,
        "remaining": len(codes),
    }
    path = ledger_path(user_id, pool_id, mode, root)
    with _lock_for(path):
        loaded = load_ledger(path)
    if not loaded:
        return empty
    if list(loaded.get("order") or []) != codes:
        empty["reason"] = "名单变了，重新开始"
        return empty
    if loaded.get("status") == "complete":
        empty["status"] = "complete"
        empty["reason"] = "上一轮已经完成，重新开始"
        empty["remaining"] = 0
        return empty
    required = required_work(field_keys, mode)
    drop = expire_ledger(loaded, moment, trading)
    if required and mark_complete(loaded, required, moment, trading):
        empty["status"] = "complete"
        empty["reason"] = "上一轮已经完成，重新开始"
        empty["remaining"] = 0
        return empty
    quoted = _quoted_count(loaded, moment, trading)
    slow_left = _slow_left(loaded, required, moment, trading)
    if drop:
        reason = drop
    else:
        reason = window.resume_banner(window.phase_at(moment, trading), quoted, len(codes), slow_left)
    pages = []
    resume_from = len(codes)
    for start in range(0, len(codes), page):
        chunk = codes[start : start + page]
        rows = []
        for code in chunk:
            row = (loaded.get("rows") or {}).get(code)
            if isinstance(row, dict) and row:
                rows.append(dict(row))
        complete = bool(chunk) and all(code_done(loaded, code, required, moment, trading) for code in chunk)
        pages.append({"index": start // page, "complete": complete, "rows": rows})
        if not complete and resume_from == len(codes):
            resume_from = start
    return {
        "status": "open",
        "reason": reason,
        "total": len(codes),
        "order": codes,
        "pages": pages,
        "resume_from": resume_from,
        "quoted": quoted,
        "remaining": max(0, len(codes) - quoted),
    }
