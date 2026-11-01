"""账本：分批写入、只作废现价、名单变化整本作废、凑齐后标记完成。"""

from datetime import datetime

from src.market.client import MarketClient, resolve_instruments
from src.query.engine import QueryEngine
from src.query.resume_ledger import ResumeSession, expire_ledger, fresh_ledger, overlay_row, peek_resume
from src.query.resume_window import SH


def at(hour: int, minute: int, day: int = 29) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=SH)


class _Inst:
    def __init__(self, code: str):
        self.code6 = code
        self.code_full = code + ".SH"
        self.name = code
        self.market = "SH"


def _open(tmp_path, order, mode="quote", fields=None, now=None):
    return ResumeSession.open(
        user_id=7,
        pool_id="exchange:sh",
        mode=mode,
        order=order,
        field_keys=fields or ["price", "pct"],
        root=tmp_path,
        now=now or at(10, 0),
    )


def test_quote_batches_keep_the_first_stamp_and_merge_prices(tmp_path, monkeypatch):
    moment = at(10, 0)
    monkeypatch.setattr("src.query.resume_window.now_shanghai", lambda: moment)
    session = _open(tmp_path, ["600519", "000001"], now=moment)
    session.note_quotes({"600519": {"p": 10, "pc": 1.2}})
    session.note_quotes({"600519": {"p": 10}, "000001": {"p": 11}})
    assert session.ledger["quotes"]["600519"] == session.ledger["quote_oldest"]
    assert session.ledger["quotes"]["000001"] == session.ledger["quote_oldest"]
    assert session.ledger["rows"]["600519"]["price"] == 10
    assert session.ledger["rows"]["000001"]["price"] == 11
    assert (tmp_path / "user_7" / "exchange_sh" / "quote.json").is_file()
    assert not (tmp_path / "user_7" / "exchange_sh" / "full.json").exists()


def test_expiring_quotes_keeps_profile_and_finance(tmp_path):
    ledger = fresh_ledger(["600519"], ["price", "industry", "eps"], "full")
    taken = at(10, 0).isoformat()
    ledger["quotes"]["600519"] = taken
    ledger["quote_oldest"] = taken
    ledger["blocks"]["600519"] = {"profile": taken, "finance": taken}
    ledger["rows"]["600519"] = {"code6": "600519", "price": 10, "industry": "食品饮料", "eps": 1.5}
    reason = expire_ledger(ledger, at(11, 31), lambda day: day.weekday() < 5)
    assert ledger["quotes"] == {}
    assert ledger["quote_oldest"] == ""
    assert "price" not in ledger["rows"]["600519"]
    assert ledger["rows"]["600519"]["industry"] == "食品饮料"
    assert ledger["rows"]["600519"]["eps"] == 1.5
    assert "11:30" in reason
    assert "行业和财务" in reason


def test_a_quote_after_the_boundary_can_stay(tmp_path):
    ledger = fresh_ledger(["600519", "000001"], ["price"], "quote")
    ledger["quotes"] = {"600519": at(11, 20).isoformat(), "000001": at(11, 35).isoformat()}
    ledger["quote_oldest"] = at(11, 20).isoformat()
    ledger["rows"] = {
        "600519": {"code6": "600519", "price": 1},
        "000001": {"code6": "000001", "price": 2},
    }
    reason = expire_ledger(ledger, at(11, 40), lambda day: day.weekday() < 5)
    assert "600519" not in ledger["quotes"]
    assert "000001" in ledger["quotes"]
    assert "price" not in ledger["rows"]["600519"]
    assert ledger["rows"]["000001"]["price"] == 2
    assert "11:30" in reason


def test_order_change_voids_the_ledger(tmp_path, monkeypatch):
    moment = at(10, 0)
    monkeypatch.setattr("src.query.resume_window.now_shanghai", lambda: moment)
    session = _open(tmp_path, ["600519", "000001"], now=moment)
    session.note_quotes({"600519": {"p": 10}})
    session.close()
    again = _open(tmp_path, ["000001", "600519"], now=moment)
    assert again.resumed is False
    assert again.reason == "名单变了，重新开始"
    assert again.ledger["quotes"] == {}


def test_a_finished_run_starts_over(tmp_path, monkeypatch):
    moment = at(10, 0)
    monkeypatch.setattr("src.query.resume_window.now_shanghai", lambda: moment)
    session = _open(tmp_path, ["600519"], now=moment)
    session.note_quotes({"600519": {"p": 10}})
    session.note_row({"code6": "600519", "price": 10, "name": "贵州茅台"}, {"quote"})
    session.close()
    assert session.ledger["status"] == "complete"
    again = _open(tmp_path, ["600519"], now=moment)
    assert again.resumed is False
    assert again.reason == "上一轮已经完成，重新开始"
    view = peek_resume(
        user_id=7,
        pool_id="exchange:sh",
        mode="quote",
        order=["600519"],
        field_keys=["price"],
        root=tmp_path,
        now=moment,
    )
    assert view["status"] == "complete"
    assert view["pages"] == []


def test_page_keeps_its_order_when_some_codes_are_still_valid(tmp_path, monkeypatch):
    moment = at(10, 0)
    monkeypatch.setattr("src.query.resume_window.now_shanghai", lambda: moment)
    order = [f"{i:06d}" for i in range(100)]
    session = _open(tmp_path, order, now=moment)
    session.ledger["quote_oldest"] = moment.isoformat()
    for code in order[:40]:
        session.ledger["quotes"][code] = moment.isoformat()
        session.ledger["rows"][code] = {"code6": code, "price": 1, "industry": "原行业"}
    insts = [_Inst(code) for code in order]
    plan = session.plan_page(insts)
    assert plan.skipped == 40
    assert plan.refetch_count == 60
    assert [inst.code6 for inst in plan.todo] == order[40:]
    fresh = [{"code6": code, "price": 2, "industry": None} for code in order[40:]]
    rows = session.stitch(insts, fresh)
    assert [row["code6"] for row in rows] == order
    assert rows[0]["price"] == 1
    assert rows[0]["industry"] == "原行业"
    assert rows[40]["price"] == 2
    assert rows[40].get("industry") in (None, "")


def test_full_mode_keeps_a_valid_quote_and_fetches_the_missing_profile(tmp_path, monkeypatch):
    moment = at(10, 0)
    monkeypatch.setattr("src.query.resume_window.now_shanghai", lambda: moment)
    session = _open(tmp_path, ["600519"], mode="full", fields=["price", "industry"], now=moment)
    session.note_quotes({"600519": {"p": 10}})
    session.ledger["rows"]["600519"]["industry"] = "食品饮料"
    plan = session.plan_page([_Inst("600519")])
    assert plan.skipped == 0
    assert plan.skip["600519"] == {"quote"}
    assert plan.refetched["600519"] == {"profile"}
    assert plan.seed["600519"]["p"] == 10
    session.note_row({"code6": "600519", "price": 10, "industry": "食品饮料"}, {"profile"})
    done = session.plan_page([_Inst("600519")])
    assert done.skipped == 1
    assert done.todo == []


def test_overlay_does_not_wipe_a_kept_profile_or_a_missing_off_low():
    merged = overlay_row(
        {"code6": "600519", "price": 1, "industry": "食品饮料", "low_long": 10},
        {"code6": "600519", "price": 15, "industry": "", "off_low": None},
        {"quote"},
    )
    assert merged["price"] == 15
    assert merged["industry"] == "食品饮料"
    assert merged["off_low"] == 50.0


def test_engine_skips_a_fresh_quote_and_keeps_the_seed_price():
    market = MarketClient()
    engine = QueryEngine(market)
    insts = resolve_instruments(["600519", "000001"], market)
    flushed: list[set[str]] = []
    rows = engine.run(
        insts,
        ["price", "industry"],
        refresh_mode="full",
        force_live=True,
        skip_blocks={"600519": {"quote"}},
        seed_quotes={"600519": {"p": 1.23, "pc": 0.5, "source": "resume"}},
        on_quote_flush=lambda got: flushed.append(set(got)),
    )
    by = {row["code6"]: row for row in rows}
    assert by["600519"]["price"] == 1.23
    assert by["600519"]["industry"] == "食品饮料"
    assert by["000001"]["price"] == 11.52
    assert flushed
    assert all("600519" not in batch for batch in flushed)
    assert any("000001" in batch for batch in flushed)
