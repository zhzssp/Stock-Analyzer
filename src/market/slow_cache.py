"""分项慢字段 TTL 缓存（profile / holders / finance / flow / indicators）。"""

from __future__ import annotations

import time
from typing import Any

from src.platform.storage import read_cache_json, write_cache_json


def _wrap(data: Any) -> dict:
    return {"fetched_at": time.time(), "data": data}


def read_fresh(key: str, ttl_sec: int) -> Any | None:
    """命中且未过期则返回 data，否则 None。"""
    if ttl_sec <= 0:
        return None
    payload = read_cache_json(key)
    if not isinstance(payload, dict) or "data" not in payload:
        return None
    fetched = float(payload.get("fetched_at") or 0)
    if time.time() - fetched > ttl_sec:
        return None
    return payload["data"]


def read_stale(key: str) -> Any | None:
    payload = read_cache_json(key)
    if not isinstance(payload, dict) or "data" not in payload:
        return None
    return payload["data"]


def write(key: str, data: Any) -> None:
    write_cache_json(key, _wrap(data))
