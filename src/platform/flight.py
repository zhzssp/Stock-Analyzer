"""每个登录用户一把槽：会打麦蕊的查询和导出同时只跑一轮。

查询换池或换动作时，旧的一轮在下一批现价之前停下，只有最新一轮接着跑。
导出不取消正在跑的查询，查询也不取消正在写的导出。已经有导出在排队或在写时，
再来一份直接拒绝。
"""

from __future__ import annotations

import threading
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Callable, Iterator


class FlightBusy(Exception):
    """同一用户已经有一份导出在进行或排队。"""


class FlightSuperseded(Exception):
    """这一轮被更新的查询替换，或调用方已经取消。"""


@dataclass
class FlightToken:
    kind: str
    user_id: int
    cancel: threading.Event
    replace: bool = False
    superseded: bool = False
    entered: bool = False


@dataclass
class _Slot:
    cv: threading.Condition = field(default_factory=threading.Condition)
    current: FlightToken | None = None
    waiters: deque[FlightToken] = field(default_factory=deque)
    export_token: FlightToken | None = None


_guard = threading.Lock()
_slots: dict[int, _Slot] = {}


def _slot(user_id: int) -> _Slot:
    with _guard:
        slot = _slots.get(user_id)
        if slot is None:
            slot = _Slot()
            _slots[user_id] = slot
        return slot


def wake(user_id: int) -> None:
    """页面断开时叫醒正在排队的那一轮，让它看到取消。"""
    slot = _slot(user_id)
    with slot.cv:
        slot.cv.notify_all()


def needs_wait(user_id: int) -> bool:
    slot = _slot(user_id)
    with slot.cv:
        return slot.current is not None or bool(slot.waiters)


def reset_for_tests() -> None:
    with _guard:
        _slots.clear()


def _drop(slot: _Slot, token: FlightToken) -> None:
    slot.waiters = deque(item for item in slot.waiters if item is not token)


def _leave(slot: _Slot, token: FlightToken) -> None:
    if token.superseded or token.cancel.is_set():
        _drop(slot, token)
        slot.cv.notify_all()
        raise FlightSuperseded()


def begin_query(
    user_id: int,
    cancel: threading.Event | None = None,
    *,
    on_queued: Callable[[], None] | None = None,
    replace: bool = False,
) -> FlightToken:
    """排队进入查询。replace 为真时取消当前查询，并换掉还在排队的替换型查询。

    不取消正在写的导出，也不挤掉「只排队、不替换」的查询（例如看一只股票的详情）。
    on_queued 在需要等待时调用，且不能再来申请这把槽。
    """
    slot = _slot(user_id)
    token = FlightToken(
        kind="query",
        user_id=user_id,
        cancel=cancel if cancel is not None else threading.Event(),
        replace=replace,
    )
    with slot.cv:
        if replace and slot.current is not None and slot.current.kind == "query":
            slot.current.cancel.set()
        if replace:
            for old in list(slot.waiters):
                if old.kind == "query" and old.replace and old is not token:
                    old.superseded = True
                    old.cancel.set()
            slot.waiters = deque(
                item for item in slot.waiters if not (item.kind == "query" and item.replace and item.superseded)
            )
        must_wait = slot.current is not None or bool(slot.waiters)
        slot.waiters.append(token)
        if must_wait and on_queued is not None:
            on_queued()
        slot.cv.notify_all()
        while True:
            _leave(slot, token)
            if slot.current is None and slot.waiters and slot.waiters[0] is token:
                slot.waiters.popleft()
                slot.current = token
                token.entered = True
                slot.cv.notify_all()
                return token
            slot.cv.wait(timeout=0.2)


def claim_export(user_id: int, cancel: threading.Event | None = None) -> FlightToken:
    """占住这一用户仅有的导出名额。已经有一份时抛 FlightBusy，不取消对方。"""
    slot = _slot(user_id)
    token = FlightToken(
        kind="export",
        user_id=user_id,
        cancel=cancel if cancel is not None else threading.Event(),
    )
    with slot.cv:
        busy = slot.export_token is not None or (slot.current is not None and slot.current.kind == "export")
        if busy:
            raise FlightBusy()
        slot.export_token = token
        slot.cv.notify_all()
        return token


def enter_export(token: FlightToken, on_queued: Callable[[], None] | None = None) -> None:
    """等当前查询和已经排上的查询结束，再开始写导出。不取消它们。"""
    slot = _slot(token.user_id)
    with slot.cv:
        if slot.export_token is not token and slot.current is not token:
            raise FlightBusy()
        if (slot.current is not None or slot.waiters) and on_queued is not None:
            on_queued()
        while slot.current is not None or slot.waiters:
            if token.cancel.is_set():
                if slot.export_token is token:
                    slot.export_token = None
                slot.cv.notify_all()
                raise FlightSuperseded()
            slot.cv.wait(timeout=0.2)
        slot.current = token
        token.entered = True
        slot.cv.notify_all()


def finish(token: FlightToken | None) -> None:
    if token is None:
        return
    slot = _slot(token.user_id)
    with slot.cv:
        if slot.current is token:
            slot.current = None
        _drop(slot, token)
        if slot.export_token is token:
            slot.export_token = None
        token.entered = False
        slot.cv.notify_all()


@contextmanager
def query_slot(
    user_id: int,
    cancel: threading.Event | None = None,
    *,
    on_queued: Callable[[], None] | None = None,
    replace: bool = False,
) -> Iterator[FlightToken]:
    token = begin_query(user_id, cancel, on_queued=on_queued, replace=replace)
    try:
        yield token
    finally:
        finish(token)


@contextmanager
def export_slot(token: FlightToken, on_queued: Callable[[], None] | None = None) -> Iterator[FlightToken]:
    try:
        enter_export(token, on_queued=on_queued)
        yield token
    finally:
        finish(token)
