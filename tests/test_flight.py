"""同一用户的查询和导出不会叠着打麦蕊。不访问网络。"""

import threading

import pytest

from src.platform.flight import (
    FlightBusy,
    FlightSuperseded,
    begin_query,
    claim_export,
    enter_export,
    finish,
    reset_for_tests,
)


def setup_function() -> None:
    reset_for_tests()


def test_only_the_latest_query_runs():
    ran: list[str] = []
    a_in = threading.Event()
    release_a = threading.Event()
    threads: list[threading.Thread] = []

    def run_a() -> None:
        token = begin_query(7, replace=True)
        try:
            ran.append("a")
            a_in.set()
            assert release_a.wait(2)
        finally:
            finish(token)

    def run_later(label: str, waiting: threading.Event) -> None:
        try:
            token = begin_query(7, on_queued=waiting.set, replace=True)
        except FlightSuperseded:
            ran.append(label + "-skip")
            return
        try:
            ran.append(label)
        finally:
            finish(token)

    try:
        first = threading.Thread(target=run_a)
        threads.append(first)
        first.start()
        assert a_in.wait(2)
        b_wait = threading.Event()
        c_wait = threading.Event()
        second = threading.Thread(target=run_later, args=("b", b_wait))
        third = threading.Thread(target=run_later, args=("c", c_wait))
        threads.extend((second, third))
        second.start()
        assert b_wait.wait(2)
        third.start()
        assert c_wait.wait(2)
        release_a.set()
    finally:
        release_a.set()
        for thread in threads:
            thread.join(2)
            assert not thread.is_alive()

    assert "a" in ran
    assert "b-skip" in ran
    assert "c" in ran
    assert "b" not in ran


def test_second_export_does_not_start():
    calls: list[str] = []
    token = claim_export(4)
    try:
        enter_export(token)
        calls.append("first")
        with pytest.raises(FlightBusy):
            other = claim_export(4)
            enter_export(other)
            calls.append("second")
    finally:
        finish(token)
    assert calls == ["first"]


def test_export_waits_and_does_not_cancel_the_query():
    order: list[str] = []
    query_cancel = threading.Event()
    entered = threading.Event()
    release = threading.Event()
    threads: list[threading.Thread] = []

    def query() -> None:
        token = begin_query(3, query_cancel, replace=True)
        try:
            order.append("query")
            entered.set()
            assert release.wait(2)
            order.append("query-cancel" if token.cancel.is_set() else "query-clean")
        finally:
            finish(token)

    def export() -> None:
        token = claim_export(3)
        try:
            enter_export(token, on_queued=lambda: order.append("export-wait"))
            order.append("export")
        finally:
            finish(token)

    try:
        first = threading.Thread(target=query)
        second = threading.Thread(target=export)
        threads.extend((first, second))
        first.start()
        assert entered.wait(2)
        second.start()
        deadline = threading.Event()
        assert deadline.wait(0.3) is False
        assert "export-wait" in order
        assert not query_cancel.is_set()
        release.set()
    finally:
        release.set()
        for thread in threads:
            thread.join(2)
            assert not thread.is_alive()

    assert order[0] == "query"
    assert "query-clean" in order
    assert order[-1] == "export"
