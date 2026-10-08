"""缓存读的内存层：进程内 LRU + (mtime_ns, size) 校验。

只加速「读」，一点语义都不改：

- 命中判定靠 stat 出来的 ``(st_mtime_ns, st_size)``，文件被外部改动或删除立刻失效；
- 命中时照样 ``os.utime()``——预算淘汰是按 mtime 排序的，跳过会把「长期读、很少写」
  的缓存（bars、慢字段）误删掉，反而多打接口；utime 之后重新取一次指纹；
- 写盘、删除、清缓存都会同步失效。

查询是并发的（ThreadPoolExecutor），所有操作都在锁内完成。
"""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Any

from src.config import settings

# 哨兵：用来区分「没缓存」与「缓存的值本身就是 None」。
MISS = object()

_SAMPLE_LIMIT = 8
_DEPTH_LIMIT = 4

_lock = threading.RLock()
# path -> [mtime_ns, file_size, payload, estimated_bytes]
_store: "OrderedDict[str, list]" = OrderedDict()
_bytes = 0
_hits = 0
_misses = 0


def enabled() -> bool:
    return bool(getattr(settings, "cache_memory_enabled", True))


def max_bytes() -> int:
    return max(1, int(float(getattr(settings, "cache_memory_max_mb", 0) or 64) * 1024 * 1024))


def _stat(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def estimate_bytes(payload: Any, depth: int = 0) -> int:
    """粗估占用。

    bars 动辄 500 根 K 线，全量遍历一遍就不叫加速了——超过抽样上限的容器
    只取前几个估个单价再乘长度，误差换来的是写入时 O(1)。
    """
    if payload is None or isinstance(payload, (bool, int, float)):
        return 32
    if isinstance(payload, str):
        return len(payload) + 49
    if depth >= _DEPTH_LIMIT:
        return 64
    if isinstance(payload, (list, tuple)):
        n = len(payload)
        if not n:
            return 64
        if n <= _SAMPLE_LIMIT:
            return 64 + sum(estimate_bytes(x, depth + 1) for x in payload)
        unit = sum(estimate_bytes(x, depth + 1) for x in payload[:_SAMPLE_LIMIT]) / _SAMPLE_LIMIT
        return 64 + int(unit * n)
    if isinstance(payload, dict):
        n = len(payload)
        if not n:
            return 64
        items = list(payload.items())
        if n <= _SAMPLE_LIMIT:
            return 64 + sum(len(str(k)) + estimate_bytes(v, depth + 1) for k, v in items)
        unit = sum(len(str(k)) + estimate_bytes(v, depth + 1) for k, v in items[:_SAMPLE_LIMIT]) / _SAMPLE_LIMIT
        return 64 + int(unit * n)
    return 64


def _drop(path: str) -> None:
    global _bytes
    entry = _store.pop(path, None)
    if entry is not None:
        _bytes -= entry[3]


def _evict() -> None:
    global _bytes
    limit = max_bytes()
    while _bytes > limit and len(_store) > 1:
        _, victim = _store.popitem(last=False)
        _bytes -= victim[3]


def get(path: str) -> Any:
    """命中返回 payload；未命中 / 已失效返回 MISS。"""
    if not enabled():
        return MISS
    global _hits, _misses
    with _lock:
        entry = _store.get(path)
        if entry is None:
            _misses += 1
            return MISS
        st = _stat(path)
        if st is None or st[0] != entry[0] or st[1] != entry[1]:
            # 文件被改过或删掉了：宁可多读一次盘，也不能把旧数据当新的用。
            _drop(path)
            _misses += 1
            return MISS
        try:
            os.utime(path, None)
        except OSError:
            pass
        else:
            fresh = _stat(path)
            if fresh is not None:
                entry[0], entry[1] = fresh
        _store.move_to_end(path)
        _hits += 1
        # 注意：返回的是同一份对象，调用方不要原地改它（现有调用点都是只读）。
        return entry[2]


def put(path: str, payload: Any) -> None:
    """写盘之后调用：内部重新 stat，所以必须在 os.utime 之后调。"""
    if not enabled():
        return
    st = _stat(path)
    if st is None:
        return
    est = estimate_bytes(payload)
    global _bytes
    with _lock:
        old = _store.get(path)
        if old is not None:
            _bytes -= old[3]
        _store[path] = [st[0], st[1], payload, est]
        _store.move_to_end(path)
        _bytes += est
        _evict()


def invalidate(path: str) -> None:
    """文件被删掉时调用。"""
    if not enabled():
        return
    with _lock:
        _drop(path)


def clear() -> None:
    global _bytes
    with _lock:
        _store.clear()
        _bytes = 0


def stats() -> dict:
    """排障用：确认「到底有没有命中」以及内存占用有没有超预算。"""
    with _lock:
        return {
            "enabled": enabled(),
            "entries": len(_store),
            "bytes": _bytes,
            "budget_bytes": max_bytes(),
            "hits": _hits,
            "misses": _misses,
        }
