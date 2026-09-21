from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.config import ROOT, settings
from src.market.normalize import Instrument, normalize_instrument

try:
    from zoneinfo import ZoneInfo

    SHANGHAI = ZoneInfo("Asia/Shanghai")
except Exception:  # pragma: no cover
    SHANGHAI = timezone(timedelta(hours=8))

QUOTE_FIELDS = ("p", "pc", "pe", "sjl", "o", "h", "l", "v", "c", "hs", "sz", "lt", "zdf60", "zdfnc")
_SAFE_LOGIN = re.compile(r"[^A-Za-z0-9._-]+")
_SLOT_NAME = re.compile(r"^(\d{4})")
POINTER_NAME = "clock_pointer.txt"
SCHEMA = 1


def interval_sec() -> int:
    return max(60, int(settings.clock_interval_sec or 300))


def now_shanghai(at: datetime | None = None) -> datetime:
    if at is None:
        return datetime.now(SHANGHAI)
    if at.tzinfo is None:
        return at.replace(tzinfo=SHANGHAI)
    return at.astimezone(SHANGHAI)


def slot_start(at: datetime | None = None) -> datetime:
    current = now_shanghai(at)
    step = interval_sec()
    midnight = current.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((current - midnight).total_seconds())
    floored = elapsed - (elapsed % step)
    return midnight + timedelta(seconds=floored)


def format_as_of(slot: datetime) -> str:
    return slot.isoformat(timespec="seconds")


def parse_as_of(value: str) -> datetime | None:
    text = (value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return now_shanghai(parsed)


def pointer_path() -> Path:
    return settings.data_dir / POINTER_NAME


def clock_dir_from_env() -> Path | None:
    raw = str(getattr(settings, "clock_dir", "") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def configured_clock_dir() -> Path | None:
    env_dir = clock_dir_from_env()
    if env_dir is not None:
        return env_dir
    path = pointer_path()
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    return Path(text).expanduser()


def clock_dir_error(path: Path) -> str | None:
    try:
        resolved = path.expanduser().resolve()
    except OSError:
        return "无法解析这个路径"
    data = settings.data_dir.resolve()
    if resolved == data:
        return "请不要把整个 data 目录当作账本，里面有数据库和密钥。"
    if resolved == ROOT.resolve():
        return "请不要把软件根目录当作账本。"
    return None


def set_clock_dir(path: Path) -> Path:
    err = clock_dir_error(path)
    if err:
        raise ValueError(err)
    target = path.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    (target / "quotes").mkdir(exist_ok=True)
    (target / "universe").mkdir(exist_ok=True)
    pointer_path().write_text(str(target), encoding="utf-8")
    return target


def ensure_layout(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "quotes").mkdir(exist_ok=True)
    (root / "universe").mkdir(exist_ok=True)


def slot_file(root: Path, slot: datetime) -> Path:
    day = now_shanghai(slot).strftime("%Y-%m-%d")
    hhmm = now_shanghai(slot).strftime("%H%M")
    return root / "quotes" / day / f"{hhmm}.json"


def _hhmm_of(name: str) -> str | None:
    match = _SLOT_NAME.match(Path(name).name)
    return match.group(1) if match else None


def _is_temp(name: str) -> bool:
    lower = name.lower()
    return lower.endswith(".tmp") or ".tmp." in lower or name in {"desktop.ini", ".ds_store"}


def _is_canonical(path: Path) -> bool:
    return bool(re.fullmatch(r"\d{4}\.json", path.name))


def _is_conflict_copy(path: Path, hhmm: str) -> bool:
    if _is_temp(path.name) or not path.name.endswith(".json"):
        return False
    if path.name == f"{hhmm}.json":
        return False
    return path.name.startswith(hhmm) and path.suffix.lower() == ".json"


def _quote_row(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for key in QUOTE_FIELDS:
        if key in raw:
            out[key] = raw[key]
    return out


def _load_json(path: Path) -> dict | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _writers_of(payload: dict) -> list[str]:
    writers = payload.get("writers")
    if isinstance(writers, list):
        return [str(x) for x in writers if str(x).strip()]
    writer = str(payload.get("writer") or "").strip()
    return [writer] if writer else []


def _normalize_payload(payload: dict, slot: datetime | None = None) -> dict:
    quotes_in = payload.get("quotes") if isinstance(payload.get("quotes"), dict) else {}
    quotes = {str(code): _quote_row(row) for code, row in quotes_in.items() if str(code).isdigit() or str(code)}
    quotes = {code: row for code, row in quotes.items() if row}
    codes = sorted(quotes)
    as_of = str(payload.get("as_of") or "")
    if not as_of and slot is not None:
        as_of = format_as_of(slot)
    return {
        "schema": int(payload.get("schema") or SCHEMA),
        "as_of": as_of,
        "interval_sec": int(payload.get("interval_sec") or interval_sec()),
        "writers": _writers_of(payload),
        "codes": codes,
        "quotes": quotes,
    }


def _read_slot_payload(root: Path, slot: datetime) -> dict | None:
    canonical = slot_file(root, slot)
    hhmm = now_shanghai(slot).strftime("%H%M")
    folder = canonical.parent
    chosen: dict | None = None
    extras: list[dict] = []
    if canonical.exists():
        loaded = _load_json(canonical)
        if loaded:
            chosen = _normalize_payload(loaded, slot)
    if folder.exists():
        for path in sorted(folder.iterdir()):
            if not path.is_file() or not _is_conflict_copy(path, hhmm):
                continue
            loaded = _load_json(path)
            if not loaded:
                continue
            extras.append(_normalize_payload(loaded, slot))
    if chosen is None and extras:
        extras.sort(key=lambda item: ",".join(item.get("writers") or []))
        chosen = extras[0]
        extras = extras[1:]
        try:
            if not canonical.exists():
                _atomic_write(canonical, chosen)
        except OSError:
            pass
    if chosen is None:
        return None
    for extra in extras:
        extra_quotes = extra.get("quotes") or {}
        merged = False
        for code, row in extra_quotes.items():
            if code not in chosen["quotes"] and row:
                chosen["quotes"][code] = row
                merged = True
        if merged:
            for writer in extra.get("writers") or []:
                if writer not in chosen["writers"]:
                    chosen["writers"].append(writer)
    if extras:
        chosen["codes"] = sorted(chosen["quotes"])
        try:
            _atomic_write(canonical, chosen)
        except OSError:
            pass
    return chosen


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def in_session(at: datetime | None = None) -> bool:
    current = now_shanghai(at)
    if current.weekday() >= 5:
        return False
    minutes = current.hour * 60 + current.minute
    return 9 * 60 <= minutes <= 15 * 60


def can_write_tape(market: Any) -> bool:
    if getattr(market, "offline", False):
        return False
    if getattr(market, "sample_only", False):
        return False
    return True


def safe_login(login: str) -> str:
    text = _SAFE_LOGIN.sub("_", (login or "").strip()).strip("._") or "user"
    return text[:64]


def universe_path(root: Path, login: str) -> Path:
    return root / "universe" / f"{safe_login(login)}.json"


def write_universe(root: Path, login: str, codes: list[str]) -> Path | None:
    try:
        ensure_layout(root)
        cleaned = sorted({str(code).split(".")[0] for code in codes if str(code).strip()})
        payload = {
            "schema": SCHEMA,
            "login": safe_login(login),
            "updated_at": format_as_of(now_shanghai()),
            "codes": cleaned,
        }
        path = universe_path(root, login)
        _atomic_write(path, payload)
        _schedule_git(root)
        return path
    except OSError:
        return None


def load_universe_codes(root: Path) -> list[str]:
    folder = root / "universe"
    if not folder.exists():
        return []
    codes: set[str] = set()
    for path in folder.glob("*.json"):
        if _is_temp(path.name):
            continue
        payload = _load_json(path)
        if not payload:
            continue
        raw = payload.get("codes") if isinstance(payload.get("codes"), list) else []
        for item in raw:
            code = str(item).split(".")[0].strip()
            if code:
                codes.add(code)
    return sorted(codes)


def list_slots(root: Path, day: str | None = None) -> list[dict]:
    quotes_root = root / "quotes"
    if not quotes_root.exists():
        return []
    days = [day] if day else sorted(p.name for p in quotes_root.iterdir() if p.is_dir())
    out: list[dict] = []
    seen: set[str] = set()
    for name in days:
        folder = quotes_root / name
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.json")):
            if _is_temp(path.name) or not _is_canonical(path):
                continue
            payload = _load_json(path)
            if not payload:
                continue
            as_of = str(payload.get("as_of") or "")
            if not as_of:
                hhmm = _hhmm_of(path.name)
                if hhmm:
                    as_of = f"{name}T{hhmm[:2]}:{hhmm[2:]}:00+08:00"
            if as_of in seen:
                continue
            seen.add(as_of)
            quotes = payload.get("quotes") if isinstance(payload.get("quotes"), dict) else {}
            out.append(
                {
                    "as_of": as_of,
                    "codes": sorted(quotes),
                    "count": len(quotes),
                    "path": str(path),
                }
            )
    out.sort(key=lambda row: row["as_of"])
    return out


def load_slot(root: Path, as_of: str) -> dict | None:
    wanted = parse_as_of(as_of)
    if wanted is None:
        return None
    return _read_slot_payload(root, slot_start(wanted))


def clock_series(root: Path, code: str, start: str, end: str) -> list[dict]:
    code6 = str(code or "").split(".")[0]
    begin = parse_as_of(start)
    finish = parse_as_of(end)
    if not code6 or begin is None or finish is None:
        return []
    if finish < begin:
        begin, finish = finish, begin
    points: list[dict] = []
    seen: set[str] = set()
    for item in list_slots(root):
        as_of = item["as_of"]
        if as_of in seen:
            continue
        stamp = parse_as_of(as_of)
        if stamp is None or stamp < begin or stamp > finish:
            continue
        payload = load_slot(root, as_of)
        if not payload:
            continue
        row = (payload.get("quotes") or {}).get(code6)
        if not row:
            continue
        seen.add(as_of)
        point = {"as_of": as_of, "code6": code6}
        point.update(_quote_row(row))
        points.append(point)
    return points


def latest_payload(root: Path) -> dict | None:
    items = list_slots(root)
    if not items:
        return None
    return load_slot(root, items[-1]["as_of"])


def merge_quotes_into_slot(
    root: Path,
    slot: datetime,
    quotes: dict[str, dict],
    writer: str = "",
) -> dict | None:
    ensure_layout(root)
    existing = _read_slot_payload(root, slot) or {
        "schema": SCHEMA,
        "as_of": format_as_of(slot_start(slot)),
        "interval_sec": interval_sec(),
        "writers": [],
        "codes": [],
        "quotes": {},
    }
    changed = False
    for code, row in quotes.items():
        code6 = str(code).split(".")[0]
        cleaned = _quote_row(row)
        if not code6 or not cleaned:
            continue
        if code6 in existing["quotes"]:
            continue
        existing["quotes"][code6] = cleaned
        changed = True
    login = safe_login(writer) if writer else ""
    if changed and login and login not in existing["writers"]:
        existing["writers"].append(login)
    elif not existing["writers"] and login:
        existing["writers"] = [login]
        changed = True
    existing["codes"] = sorted(existing["quotes"])
    existing["as_of"] = existing.get("as_of") or format_as_of(slot_start(slot))
    existing["interval_sec"] = int(existing.get("interval_sec") or interval_sec())
    existing["schema"] = int(existing.get("schema") or SCHEMA)
    if not existing["quotes"]:
        return existing
    try:
        _atomic_write(slot_file(root, slot), existing)
    except OSError:
        return existing
    if changed:
        _schedule_git(root)
    return existing


def _decorate(row: dict, source: str, as_of: str) -> dict:
    out = dict(row)
    out["source"] = source
    out["as_of"] = as_of
    return out


def universe_cap() -> int:
    return max(1, int(settings.query_sync_limit or 40) * 4)


def _git_payload() -> dict:
    try:
        from src.market.clock_git import git_status_payload

        return git_status_payload()
    except Exception:
        return {"enabled": False, "ok": None, "reason": ""}


def _schedule_git(clock_dir: Path | None = None) -> None:
    try:
        from src.market.clock_git import schedule_flush

        schedule_flush(clock_dir)
    except Exception:
        return


def status(root: Path | None = None) -> dict:
    target = root if root is not None else configured_clock_dir()
    if target is None:
        return {
            "enabled": False,
            "clock_dir": "",
            "writable": False,
            "as_of": "",
            "slot_count": 0,
            "reason": "未选择账本文件夹",
            "git": _git_payload(),
        }
    err = clock_dir_error(target)
    writable = False
    if not err:
        try:
            ensure_layout(target)
            writable = os.access(target, os.W_OK)
        except OSError:
            writable = False
    latest = latest_payload(target) if target.exists() else None
    slots = list_slots(target) if target.exists() else []
    return {
        "enabled": True,
        "clock_dir": str(target),
        "writable": writable and not err,
        "as_of": (latest or {}).get("as_of") or "",
        "slot_count": len(slots),
        "codes": (latest or {}).get("codes") or [],
        "reason": err or "",
        "interval_sec": interval_sec(),
        "git": _git_payload(),
    }


def align_quotes(
    market: Any,
    instruments: list[Instrument],
    writer: str = "",
    extra_codes: list[str] | None = None,
    clock_dir: Path | None = None,
    at: datetime | None = None,
    force_live: bool = False,
) -> tuple[dict[str, dict], dict]:
    """Return live quotes keyed by code6, preferring the current wall-clock slot file.

    When ``force_live`` is True (工作台打开/点刷新)，跳过墙钟档口缓存，直接向麦蕊拉现价。
    """
    insts = list(instruments)
    slot = slot_start(at)
    as_of = format_as_of(slot)
    meta = {
        "as_of": as_of,
        "source": "live",
        "enabled": False,
        "wrote": False,
        "reason": "",
    }
    if not insts:
        return {}, meta

    root = clock_dir if clock_dir is not None else configured_clock_dir()
    file_quotes: dict[str, dict] = {}
    if root is not None and not force_live:
        meta["enabled"] = True
        payload = _read_slot_payload(root, slot)
        if payload:
            file_quotes = dict(payload.get("quotes") or {})
            meta["as_of"] = payload.get("as_of") or as_of
            as_of = meta["as_of"]
    elif root is not None:
        meta["enabled"] = True

    need = [inst for inst in insts]
    covered = bool(need) and not force_live and all((inst.code6 in file_quotes) for inst in need)
    if covered:
        meta["source"] = "clock"
        return {inst.code6: _decorate(file_quotes[inst.code6], "clock", as_of) for inst in need}, meta

    missing = [inst for inst in need if force_live or inst.code6 not in file_quotes]
    fetch_list = list(missing)
    if root is not None:
        union = extra_codes if extra_codes is not None else load_universe_codes(root)
        if len(union) > universe_cap():
            union = [inst.code6 for inst in need]
        have = {inst.code6 for inst in fetch_list}
        for code in union:
            code6 = str(code).split(".")[0]
            if not code6 or code6 in file_quotes or code6 in have:
                continue
            fetch_list.append(normalize_instrument(code6))
            have.add(code6)

    live: dict[str, dict] = {}
    if fetch_list:
        try:
            live = market.quotes_many(fetch_list) or {}
        except Exception as exc:
            meta["reason"] = str(exc)
            live = {}

    out: dict[str, dict] = {}
    for inst in need:
        if not force_live and inst.code6 in file_quotes:
            out[inst.code6] = _decorate(file_quotes[inst.code6], "clock", as_of)
        elif inst.code6 in live:
            out[inst.code6] = _decorate(live[inst.code6], live[inst.code6].get("source") or "live", as_of)
        else:
            out[inst.code6] = _decorate({}, "missing", as_of)

    if root is not None and can_write_tape(market) and in_session(at) and live:
        fresh = {code: row for code, row in live.items() if code not in file_quotes}
        if fresh:
            saved = merge_quotes_into_slot(root, slot, fresh, writer=writer)
            meta["wrote"] = bool(saved)
    elif root is None:
        meta["reason"] = meta["reason"] or "未选择账本文件夹"
    elif not can_write_tape(market):
        meta["reason"] = meta["reason"] or "离线或演示 licence 不写档案"

    if any(row.get("source") == "clock" for row in out.values()):
        meta["source"] = "mixed" if any(row.get("source") != "clock" for row in out.values()) else "clock"
    else:
        meta["source"] = "live"
    return out, meta
