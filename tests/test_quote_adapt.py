"""现价按批/逐只切换。全部用假客户端，不打麦蕊。"""

import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.config import settings
from src.market.client import (
    QUOTE_BATCH_SIZE,
    LicenceExhaustedError,
    MarketClient,
    MarketError,
    QuoteBatchDowngrade,
)
from src.market.clock import SHANGHAI, align_quotes
from src.market.normalize import normalize_instrument


def _bare() -> MarketClient:
    client = MarketClient.__new__(MarketClient)
    client.offline = False
    client.sample_only = False
    client.licence = ""
    client.status = "unchecked"
    client._unusable = set()
    client.last_quote_error = ""
    client._quote_stop = False
    client._quotes_partial = {}
    return client


def _codes(n: int) -> list[SimpleNamespace]:
    return [SimpleNamespace(code6=f"{i:02d}") for i in range(n)]


def test_downgrade_then_upgrade_widens_the_next_gap(monkeypatch):
    """第一批留下；批量失败改逐只；连续成功后再按批。再失败则间隔加倍。"""
    monkeypatch.setattr(settings, "quote_batch_upgrade_after", 3)
    client = _bare()
    insts = _codes(16)
    batches: list[list[str]] = []
    singles: list[str] = []

    def batch(chunk):
        codes = [i.code6 for i in chunk]
        batches.append(codes)
        if len(batches) in (2, 3):
            raise QuoteBatchDowngrade("批量失败")
        return {code: {"p": 1, "pc": 0.1} for code in codes}

    def one(inst):
        singles.append(inst.code6)
        if inst.code6 == "04":
            raise MarketError("这一只没有行情")
        return {"p": 2, "pc": 0.2}

    with patch("src.market.client.QUOTE_BATCH_SIZE", 2):
        with patch.object(client, "_quotes_batch", side_effect=batch):
            with patch.object(client, "quote", side_effect=one):
                out = client.quotes_many(insts)

    assert batches == [["00", "01"], ["02", "03"], ["08", "09"], ["14", "15"]]
    assert singles == ["02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12", "13"]
    assert out["00"]["p"] == 1
    assert out["08"]["p"] == 2
    assert out["14"]["p"] == 1
    assert "04" not in out
    assert client.last_quote_error == "批量失败"


def test_batch_fills_a_few_gaps_and_downgrades_when_most_are_empty():
    client = _bare()
    insts = _codes(4)
    payload = [
        {"dm": "00", "p": 1, "pc": 0.1},
        {"dm": "01", "p": 0, "pc": None},
        {"dm": "02", "p": None, "pc": None},
    ]
    with patch.object(client, "_get", return_value=payload):
        with patch.object(client, "quote", return_value={"p": 9, "pc": 1}) as one:
            mapped = client._quotes_batch(insts)
    assert one.call_count == 2
    assert mapped["01"]["p"] == 0
    assert mapped["02"]["p"] == 9
    assert mapped["03"]["p"] == 9

    sparse = [{"dm": "00", "p": 1, "pc": 0.1}]
    with patch.object(client, "_get", return_value=sparse):
        with patch.object(client, "quote") as one:
            with pytest.raises(QuoteBatchDowngrade):
                client._quotes_batch(insts)
    one.assert_not_called()


def test_quota_stop_keeps_prices_already_fetched():
    client = _bare()
    insts = _codes(4)

    def batch(chunk):
        if chunk[0].code6 == "02":
            raise LicenceExhaustedError("额度已用尽")
        return {i.code6: {"p": 1, "pc": 0.2} for i in chunk}

    with patch("src.market.client.QUOTE_BATCH_SIZE", 2):
        with patch.object(client, "_quotes_batch", side_effect=batch):
            out = client.quotes_many(insts)
    assert out["00"]["p"] == 1
    assert out["01"]["p"] == 1
    assert "02" not in out
    assert "额度已用尽" in client.last_quote_error
    assert QUOTE_BATCH_SIZE == 20


def test_align_keeps_partial_quotes(tmp_path):
    at = datetime(2026, 9, 18, 10, 8, tzinfo=SHANGHAI)
    first = normalize_instrument("600038.SH", "中直")
    second = normalize_instrument("000001.SZ", "平安")

    class Partial:
        offline = False
        sample_only = False
        last_quote_error = "批量现价失败"

        def quotes_many(self, insts, cancel=None):
            return {insts[0].code6: {"p": 1.5, "pc": 0.2, "source": "live"}}

    out, meta = align_quotes(
        Partial(), [first, second], writer="hanish", clock_dir=tmp_path, at=at, force_live=True
    )
    assert out["600038"]["p"] == 1.5
    assert out["000001"]["source"] == "missing"
    assert meta["reason"] == "批量现价失败"

    class Boom:
        offline = False
        sample_only = False

        def quotes_many(self, insts, cancel=None):
            self._quotes_partial = {insts[0].code6: {"p": 3, "pc": 1, "source": "live"}}
            raise RuntimeError("连接中断")

    out2, meta2 = align_quotes(
        Boom(), [first, second], writer="hanish", clock_dir=tmp_path, at=at, force_live=True
    )
    assert out2["600038"]["p"] == 3
    assert "连接中断" in meta2["reason"]


def test_refresh_status_names_missing_prices():
    html = Path("docs/frontend/index.html").read_text(encoding="utf-8")
    assert "现价没有取到" in html


def test_cancel_stops_before_the_next_batch():
    """第一批回来之后取消，第二批不再发，已经拿到的价格还在。"""
    client = _bare()
    insts = _codes(4)
    batches: list[list[str]] = []
    cancel = threading.Event()

    def batch(chunk):
        codes = [i.code6 for i in chunk]
        batches.append(codes)
        if len(batches) == 1:
            cancel.set()
        return {code: {"p": 1, "pc": 0.1} for code in codes}

    with patch("src.market.client.QUOTE_BATCH_SIZE", 2):
        with patch.object(client, "_quotes_batch", side_effect=batch):
            out = client.quotes_many(insts, cancel=cancel)

    assert batches == [["00", "01"]]
    assert out["00"]["p"] == 1
    assert "02" not in out
