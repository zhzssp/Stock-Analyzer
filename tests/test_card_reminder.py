"""决策卡「提醒日期」：到当天提一次，同一天同一只不重复，预览不落库。"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.agents.watcher import _rule_card_reminders
from src.db import Base
from src.models import Alert


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _item(code6: str, remind_at: str, note: str = ""):
    return SimpleNamespace(code6=code6, name="测试" + code6, remind_at=remind_at, remind_note=note)


def test_card_reminder_due_today_fires_once():
    db = _session()
    user = SimpleNamespace(id=1)
    today = date.today().isoformat()
    items = [
        _item("600038", today, "看季报"),   # 到期
        _item("000001", "2099-01-01"),     # 未到期
        _item("300750", ""),               # 没填日期
    ]

    first = _rule_card_reminders(db, user, items, True)
    assert len(first) == 1

    rec = db.query(Alert).first()
    assert rec is not None
    assert rec.job_key == "card-remind"
    assert rec.code6 == "600038"
    assert "看季报" in (rec.detail or "")

    # 同一天再跑：靠已有提醒去重，不重复进今日
    assert _rule_card_reminders(db, user, items, True) == []
    assert db.query(Alert).count() == 1


def test_card_reminder_preview_does_not_persist():
    db = _session()
    items = [_item("600038", date.today().isoformat())]
    assert _rule_card_reminders(db, SimpleNamespace(id=1), items, True, preview_spec={}) == []
    assert db.query(Alert).count() == 0
