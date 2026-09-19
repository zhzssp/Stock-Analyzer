from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from src.config import settings
from src.models import Artifact

_SAFE_KEY = re.compile(r"[^A-Za-z0-9._-]+")
PROTECTED_CACHE = {"list_hs", "list_bj"}


def human_bytes(n: int | float | None) -> str:
    value = max(0, int(n or 0))
    for unit, size in (("GB", 1024**3), ("MB", 1024**2), ("KB", 1024)):
        if value >= size:
            text = value / size
            return f"{text:.1f} {unit}"
    return f"{value} B"


def path_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        try:
            return path.stat().st_size
        except OSError:
            return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                continue
    return total


def cache_file(key: str, cache_dir: Path | None = None) -> Path:
    raw = (key or "").strip()
    safe = _SAFE_KEY.sub("_", raw).strip("._") or "unknown"
    return (cache_dir or settings.cache_dir) / f"{safe}.json"


def read_cache_json(key: str, cache_dir: Path | None = None) -> Any | None:
    path = cache_file(key, cache_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    try:
        os.utime(path, None)
    except OSError:
        pass
    return payload


def write_cache_json(key: str, payload: Any, cache_dir: Path | None = None, max_bytes: int | None = None) -> Path:
    path = cache_file(key, cache_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    enforce_cache_budget(cache_dir=path.parent, max_bytes=max_bytes)
    return path


def trim_bars(rows: list | None, max_bars: int | None = None) -> list:
    items = [row for row in (rows or []) if isinstance(row, dict)]
    limit = max_bars if max_bars is not None else settings.bars_max
    keep = max(1, int(limit or 1))
    return items[-keep:]


def _cache_files(cache_dir: Path) -> list[Path]:
    if not cache_dir.exists():
        return []
    return [p for p in cache_dir.glob("*.json") if p.is_file()]


def _cache_tier(path: Path) -> int:
    key = path.stem
    if key in PROTECTED_CACHE:
        return 2
    if key.startswith("index_"):
        return 1
    return 0


def enforce_cache_budget(cache_dir: Path | None = None, max_bytes: int | None = None) -> dict:
    folder = cache_dir or settings.cache_dir
    budget = max_bytes if max_bytes is not None else settings.cache_max_bytes
    files = _cache_files(folder)
    total = sum(path_bytes(p) for p in files)
    deleted: list[str] = []
    if total <= budget:
        return {"ok": True, "bytes": total, "budget": budget, "deleted": deleted, "files": len(files)}
    ranked = sorted(files, key=lambda p: (_cache_tier(p), p.stat().st_mtime, p.name))
    remaining = list(ranked)
    for path in ranked:
        if total <= budget or len(remaining) <= 1:
            break
        size = path_bytes(path)
        try:
            path.unlink()
        except OSError:
            continue
        total -= size
        remaining.remove(path)
        deleted.append(path.stem)
    return {"ok": True, "bytes": max(0, total), "budget": budget, "deleted": deleted, "files": len(_cache_files(folder))}


def clear_cache(cache_dir: Path | None = None) -> dict:
    folder = cache_dir or settings.cache_dir
    deleted = 0
    bytes_freed = 0
    for path in _cache_files(folder):
        size = path_bytes(path)
        try:
            path.unlink()
        except OSError:
            continue
        deleted += 1
        bytes_freed += size
    return {"ok": True, "deleted": deleted, "bytes_freed": bytes_freed}


def _as_json_list(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value or [], ensure_ascii=False)


def _unlink(path: str | Path | None) -> bool:
    if not path:
        return False
    target = Path(path)
    if not target.exists():
        return False
    try:
        target.unlink()
        return True
    except OSError:
        return False


def _purge_orphan_xlsx(db: Session, artifact_dir: Path | None = None) -> int:
    folder = artifact_dir or settings.artifact_dir
    if not folder.exists():
        return 0
    kept = {str(Path(row.path)) for row in db.query(Artifact).all() if row.path}
    removed = 0
    for path in folder.glob("*.xlsx"):
        if str(path) in kept:
            continue
        if _unlink(path):
            removed += 1
    return removed


def prune_artifacts(
    db: Session,
    user_id: int | None = None,
    keep: int | None = None,
    artifact_dir: Path | None = None,
) -> dict:
    limit = keep if keep is not None else max(1, int(settings.artifact_keep))
    if user_id is not None:
        user_ids = [user_id]
    else:
        user_ids = [row[0] for row in db.query(Artifact.user_id).distinct().all()]
    removed = 0
    for uid in user_ids:
        rows = (
            db.query(Artifact)
            .filter_by(user_id=uid)
            .order_by(Artifact.created_at.desc(), Artifact.id.desc())
            .all()
        )
        for rec in rows[limit:]:
            _unlink(rec.path)
            db.delete(rec)
            removed += 1
    ghosts = 0
    q = db.query(Artifact)
    if user_id is not None:
        q = q.filter_by(user_id=user_id)
    for rec in q.all():
        if rec.path and not Path(rec.path).exists():
            db.delete(rec)
            ghosts += 1
    db.commit()
    orphans = _purge_orphan_xlsx(db, artifact_dir=artifact_dir)
    return {"ok": True, "removed": removed, "ghosts": ghosts, "orphans": orphans, "keep": limit}


def record_artifact(
    db: Session,
    *,
    user_id: int,
    path: Path | str,
    pool_name: str = "",
    field_keys: Any = None,
    codes: Any = None,
    filename: str | None = None,
) -> Artifact:
    target = Path(path)
    rec = Artifact(
        user_id=user_id,
        path=str(target),
        filename=filename or target.name,
        pool_name=pool_name or "",
        field_keys=_as_json_list(field_keys),
        codes=_as_json_list(codes),
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    prune_artifacts(db, user_id=user_id)
    fresh = db.get(Artifact, rec.id)
    return fresh or rec


def trim_alerts_log(path: Path | None = None, max_bytes: int | None = None) -> dict:
    target = path or (settings.data_dir / "alerts.log")
    budget = max_bytes if max_bytes is not None else settings.alerts_log_max_bytes
    if not target.exists():
        return {"ok": True, "bytes": 0, "trimmed": False}
    size = path_bytes(target)
    if size <= budget:
        return {"ok": True, "bytes": size, "trimmed": False}
    keep = max(32 * 1024, budget // 4)
    data = target.read_bytes()[-keep:]
    newline = data.find(b"\n")
    if newline >= 0:
        data = data[newline + 1 :]
    target.write_bytes(data)
    return {"ok": True, "bytes": path_bytes(target), "trimmed": True}


def usage() -> dict:
    data_dir = settings.data_dir
    cache_dir = settings.cache_dir
    artifact_dir = settings.artifact_dir
    db_path = settings.db_path
    log_path = data_dir / "alerts.log"
    cache_files = _cache_files(cache_dir)
    cache_bytes = sum(path_bytes(p) for p in cache_files)
    artifact_bytes = path_bytes(artifact_dir)
    db_bytes = path_bytes(db_path)
    log_bytes = path_bytes(log_path)
    total = path_bytes(data_dir)
    over = cache_bytes > settings.cache_max_bytes
    return {
        "data_dir": str(data_dir),
        "db_bytes": db_bytes,
        "cache_bytes": cache_bytes,
        "artifact_bytes": artifact_bytes,
        "log_bytes": log_bytes,
        "total_bytes": total,
        "db_human": human_bytes(db_bytes),
        "cache_human": human_bytes(cache_bytes),
        "artifact_human": human_bytes(artifact_bytes),
        "log_human": human_bytes(log_bytes),
        "total_human": human_bytes(total),
        "cache_files": len(cache_files),
        "artifact_files": len(list(artifact_dir.glob("*.xlsx"))) if artifact_dir.exists() else 0,
        "cache_over_budget": over,
        "limits": {
            "cache_max_mb": settings.cache_max_mb,
            "cache_max_bytes": settings.cache_max_bytes,
            "cache_max_human": human_bytes(settings.cache_max_bytes),
            "artifact_keep": max(1, int(settings.artifact_keep)),
            "bars_max": max(1, int(settings.bars_max)),
            "alerts_log_max_mb": settings.alerts_log_max_mb,
        },
    }


def health_storage() -> dict:
    snap = usage()
    return {
        "total_bytes": snap["total_bytes"],
        "total_human": snap["total_human"],
        "cache_over_budget": snap["cache_over_budget"],
    }


def enforce_all(db: Session, user_id: int | None = None) -> dict:
    cache = enforce_cache_budget()
    artifacts = prune_artifacts(db, user_id=user_id)
    log = trim_alerts_log()
    return {"ok": True, "cache": cache, "artifacts": artifacts, "log": log, "usage": usage()}
