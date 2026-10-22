"""把仍停在旧默认上的列设置改成十七列研究预设。只做一次。"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from src.config import settings
from src.models import FieldPref
from src.query.presets import PRESET_CUSTOM, PRESET_RESEARCH, PRESET_WATCH, keys_for_preset

_MARKER = "column_default_research"


def apply_column_default(db: Session) -> None:
    marker = settings.data_dir / _MARKER
    if marker.exists():
        return
    research = keys_for_preset(PRESET_RESEARCH)
    watch = keys_for_preset(PRESET_WATCH)
    payload = json.dumps(research, ensure_ascii=False)
    for pref in db.query(FieldPref).all():
        preset = (pref.preset or "").strip().lower()
        if preset == PRESET_CUSTOM:
            continue
        try:
            saved = json.loads(pref.field_keys or "[]")
        except json.JSONDecodeError:
            saved = []
        if not isinstance(saved, list):
            saved = []
        saved = [str(k) for k in saved]
        # 看盘名下存着另一份勾选（既不是六列，也不是旧的超集研究列）时保留。
        if preset == PRESET_WATCH and saved and saved != watch and not set(research).issubset(saved):
            continue
        pref.preset = PRESET_RESEARCH
        pref.field_keys = payload
    db.commit()
    marker.write_text("17\n", encoding="utf-8")
