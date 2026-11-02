"""现价 90 分钟、时段边界，以及慢字段各自的截止时间。"""

from datetime import date, datetime

from src.query.resume_window import SH, block_reusable, phase_at, quote_reusable


def at(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=SH)


def test_phase_boundaries_on_a_trading_thursday():
    day = date(2026, 10, 29)
    assert phase_at(at(day, 9, 14)) == "post_close"
    assert phase_at(at(day, 9, 15)) == "open_auction"
    assert phase_at(at(day, 9, 24)) == "open_auction"
    assert phase_at(at(day, 9, 25)) == "open_fixed"
    assert phase_at(at(day, 9, 30)) == "morning"
    assert phase_at(at(day, 11, 29)) == "morning"
    assert phase_at(at(day, 11, 30)) == "lunch"
    assert phase_at(at(day, 12, 59)) == "lunch"
    assert phase_at(at(day, 13, 0)) == "afternoon"
    assert phase_at(at(day, 14, 56)) == "afternoon"
    assert phase_at(at(day, 14, 57)) == "close_auction"
    assert phase_at(at(day, 15, 0)) == "post_close"
    assert phase_at(at(date(2026, 10, 31), 11, 0)) == "post_close"


def test_morning_quote_reaches_1120_and_stops_at_1131():
    day = date(2026, 10, 29)
    taken = at(day, 10, 0)
    assert quote_reusable(taken, at(day, 11, 20), taken)
    assert not quote_reusable(taken, at(day, 11, 31), taken)


def test_afternoon_quote_does_not_cross_the_close():
    day = date(2026, 10, 29)
    taken = at(day, 14, 50)
    assert quote_reusable(taken, at(day, 14, 56), taken)
    assert not quote_reusable(taken, at(day, 15, 5), taken)


def test_after_close_quote_lasts_ninety_minutes():
    day = date(2026, 10, 29)
    taken = at(day, 15, 10)
    assert quote_reusable(taken, at(day, 16, 30), taken)
    assert quote_reusable(taken, at(day, 16, 40), taken)
    assert not quote_reusable(taken, at(day, 16, 41), taken)


def test_open_auction_never_resumes_and_fixed_price_stops_at_0930():
    day = date(2026, 10, 29)
    auction = at(day, 9, 20)
    assert not quote_reusable(auction, at(day, 9, 22), auction)
    fixed = at(day, 9, 26)
    assert quote_reusable(fixed, at(day, 9, 29), fixed)
    assert not quote_reusable(fixed, at(day, 9, 30), fixed)


def test_flow_uses_the_earlier_of_one_hour_and_phase_end():
    day = date(2026, 10, 29)
    morning = at(day, 10, 0)
    assert block_reusable("flow", morning, at(day, 10, 59))
    assert not block_reusable("flow", morning, at(day, 11, 0))
    late = at(day, 11, 0)
    assert block_reusable("indicators", late, at(day, 11, 29))
    assert not block_reusable("indicators", late, at(day, 11, 30))


def test_intraday_bars_expire_at_the_close():
    day = date(2026, 10, 29)
    taken = at(day, 10, 0)
    assert block_reusable("bars", taken, at(day, 14, 59))
    assert not block_reusable("bars", taken, at(day, 15, 0))


def test_bars_after_the_close_last_until_the_next_open():
    taken = at(date(2026, 10, 30), 15, 10)
    assert block_reusable("bars", taken, at(date(2026, 11, 2), 9, 14))
    assert not block_reusable("bars", taken, at(date(2026, 11, 2), 9, 15))


def test_profile_stops_at_the_next_open_when_that_is_sooner_than_a_day():
    taken = at(date(2026, 10, 26), 10, 0)
    assert block_reusable("profile", taken, at(date(2026, 10, 27), 9, 14))
    assert not block_reusable("holders", taken, at(date(2026, 10, 27), 9, 15))
    assert not block_reusable("finance", taken, at(date(2026, 10, 27), 9, 15))


def test_profile_also_stops_at_twenty_four_hours():
    taken = at(date(2026, 10, 30), 16, 0)
    assert block_reusable("profile", taken, at(date(2026, 10, 31), 15, 59))
    assert not block_reusable("profile", taken, at(date(2026, 10, 31), 16, 0))


def test_resume_banner_states_what_is_left_without_sounding_in_progress():
    from src.query.resume_window import resume_banner

    assert resume_banner("post_close", 837, 936, False) == "收盘后 · 已有 837 只现价，还剩 99 只没取"
    assert resume_banner("post_close", 936, 936, True) == "收盘后 · 现价都还在，资料还没补完"
    assert resume_banner("post_close", 936, 936, False) == ""


def test_finished_resume_replaces_the_opening_plan():
    from pathlib import Path

    from src.query.resume_ledger import ResumeSession, fresh_ledger

    ledger = fresh_ledger(["000001"], ["price"], "quote")
    ledger["status"] = "complete"
    session = ResumeSession(
        Path("quote.json"),
        ledger,
        {"quote"},
        lambda _day: True,
        True,
        "收盘后 · 已有 1 只现价，还剩 1 只没取",
    )
    shown = session.public()
    assert shown["done"] is True
    assert shown["reason"] == "续传已完成"


def test_a_closed_weekday_does_not_count_as_the_next_open():
    closed = {date(2026, 10, 28)}

    def trading(day: date) -> bool:
        return day.weekday() < 5 and day not in closed

    taken = at(date(2026, 10, 27), 15, 10)
    assert block_reusable("bars", taken, at(date(2026, 10, 29), 9, 14), trading)
    assert not block_reusable("bars", taken, at(date(2026, 10, 29), 9, 15), trading)
