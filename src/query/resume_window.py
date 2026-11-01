"""断点续传的时间窗。现价只在同一交易时段内、且不早于本轮最早一笔超过 90 分钟时能接着用。

慢字段各自计时，并且不能跨过下一交易日 09:15。时段边界（09:25、09:30、11:30、13:00、14:57、15:00）一过，上一时段的现价就不能再混进这张表。
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

SH = ZoneInfo("Asia/Shanghai")
QUOTE_WINDOW = timedelta(minutes=90)
SLOW_DAY = timedelta(hours=24)
FLOW_WINDOW = timedelta(hours=1)

NEVER_RESUME = frozenset({"open_auction", "close_auction"})

PHASE_LABEL = {
    "post_close": "收盘后",
    "open_auction": "开盘集合竞价",
    "open_fixed": "开盘固定价",
    "morning": "上午连续竞价",
    "lunch": "午间休市",
    "afternoon": "下午连续竞价",
    "close_auction": "收盘集合竞价",
}

_SLOW_NAMES = (
    ("profile", "行业"),
    ("holders", "股东"),
    ("finance", "财务"),
    ("flow", "资金流"),
    ("indicators", "阶段涨跌"),
    ("bars", "日线"),
)


def now_shanghai() -> datetime:
    return datetime.now(SH)


def shanghai(moment: datetime) -> datetime:
    if moment.tzinfo is None:
        return moment.replace(tzinfo=SH)
    return moment.astimezone(SH)


def weekday_trading(day: date) -> bool:
    return day.weekday() < 5


def _minutes(local: datetime) -> int:
    return local.hour * 60 + local.minute


def phase_at(moment: datetime, is_trading=weekday_trading) -> str:
    local = shanghai(moment)
    if not is_trading(local.date()):
        return "post_close"
    minutes = _minutes(local)
    if minutes < 9 * 60 + 15:
        return "post_close"
    if minutes < 9 * 60 + 25:
        return "open_auction"
    if minutes < 9 * 60 + 30:
        return "open_fixed"
    if minutes < 11 * 60 + 30:
        return "morning"
    if minutes < 13 * 60:
        return "lunch"
    if minutes < 14 * 60 + 57:
        return "afternoon"
    if minutes < 15 * 60:
        return "close_auction"
    return "post_close"


def next_session_open(moment: datetime, is_trading=weekday_trading) -> datetime:
    local = shanghai(moment)
    day = local.date()
    if is_trading(day) and _minutes(local) < 9 * 60 + 15:
        return datetime.combine(day, time(9, 15), tzinfo=SH)
    cur = day + timedelta(days=1)
    for _ in range(14):
        if is_trading(cur):
            return datetime.combine(cur, time(9, 15), tzinfo=SH)
        cur += timedelta(days=1)
    return datetime.combine(cur, time(9, 15), tzinfo=SH)


def phase_end(moment: datetime, is_trading=weekday_trading) -> datetime:
    local = shanghai(moment)
    phase = phase_at(local, is_trading)
    day = local.date()

    def at(hour: int, minute: int) -> datetime:
        return datetime.combine(day, time(hour, minute), tzinfo=SH)

    if phase == "open_auction":
        return at(9, 25)
    if phase == "open_fixed":
        return at(9, 30)
    if phase == "morning":
        return at(11, 30)
    if phase == "lunch":
        return at(13, 0)
    if phase == "afternoon":
        return at(14, 57)
    if phase == "close_auction":
        return at(15, 0)
    return next_session_open(local, is_trading)


def quote_reusable(done_at: datetime, now: datetime, oldest: datetime, is_trading=weekday_trading) -> bool:
    done = shanghai(done_at)
    current = shanghai(now)
    anchor = shanghai(oldest)
    done_phase = phase_at(done, is_trading)
    now_phase = phase_at(current, is_trading)
    if done_phase != now_phase:
        return False
    if done_phase in NEVER_RESUME or now_phase in NEVER_RESUME:
        return False
    if current - anchor > QUOTE_WINDOW:
        return False
    return True


def _boundary(old_phase: str, new_phase: str) -> str:
    table = {
        ("post_close", "open_auction"): "09:15",
        ("post_close", "open_fixed"): "09:15",
        ("post_close", "morning"): "09:15",
        ("open_auction", "open_fixed"): "09:25",
        ("open_auction", "morning"): "09:25",
        ("open_fixed", "morning"): "09:30",
        ("morning", "lunch"): "11:30",
        ("morning", "afternoon"): "11:30",
        ("lunch", "afternoon"): "13:00",
        ("afternoon", "close_auction"): "14:57",
        ("afternoon", "post_close"): "15:00",
        ("close_auction", "post_close"): "15:00",
    }
    return table.get((old_phase, new_phase), "09:15")


def quote_drop_reason(oldest: datetime, now: datetime, is_trading=weekday_trading) -> str:
    """这轮最早一笔现价为什么不能再接着用。能用时返回空字符串。"""
    if quote_reusable(oldest, now, oldest, is_trading):
        return ""
    old_phase = phase_at(oldest, is_trading)
    now_phase = phase_at(now, is_trading)
    if old_phase != now_phase:
        return f"上一轮现价已跨过 {_boundary(old_phase, now_phase)}，现价重新取"
    if old_phase in NEVER_RESUME or now_phase in NEVER_RESUME:
        return "集合竞价期间不续传现价"
    return "现价已过 90 分钟，现价重取"


def partial_quote_reason(dropped_at: datetime, now: datetime, is_trading=weekday_trading) -> str:
    """只丢掉跨过边界的那一部分现价时用的短句。"""
    old_phase = phase_at(dropped_at, is_trading)
    now_phase = phase_at(now, is_trading)
    if old_phase != now_phase:
        label = PHASE_LABEL.get(old_phase, "上一轮")
        return f"已跨过 {_boundary(old_phase, now_phase)}，{label}的现价不能接着用"
    if old_phase in NEVER_RESUME or now_phase in NEVER_RESUME:
        return "集合竞价期间不续传现价"
    return "现价已过 90 分钟，现价重取"


def block_deadline(kind: str, done_at: datetime, is_trading=weekday_trading) -> datetime | None:
    local = shanghai(done_at)
    if kind in ("profile", "holders", "finance"):
        return min(local + SLOW_DAY, next_session_open(local, is_trading))
    if kind in ("flow", "indicators"):
        return min(local + FLOW_WINDOW, phase_end(local, is_trading))
    if kind == "bars":
        if is_trading(local.date()) and _minutes(local) < 15 * 60:
            return datetime.combine(local.date(), time(15, 0), tzinfo=SH)
        return next_session_open(local, is_trading)
    return None


def block_reusable(kind: str, done_at: datetime, now: datetime, is_trading=weekday_trading) -> bool:
    deadline = block_deadline(kind, done_at, is_trading)
    if deadline is None:
        return False
    return shanghai(now) < deadline


def slow_phrase(kinds: set[str]) -> str:
    names = [label for kind, label in _SLOW_NAMES if kind in kinds]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]}和{names[1]}"
    return "、".join(names[:-1]) + "和" + names[-1]


def resume_banner(phase: str, quoted: int, total: int, slow_left: bool) -> str:
    label = PHASE_LABEL.get(phase, "")
    if total <= 0 or quoted <= 0:
        return ""
    left = total - quoted
    if left <= 0 and slow_left:
        return f"续传 · {label} · 现价都还在，继续补剩下的资料"
    if left <= 0:
        return ""
    return f"续传 · {label} · 已有 {quoted} 只现价，继续剩下的 {left} 只"
