"""麦蕊 Licence 队列：当日 429/101 后换下一张，次日自动重置。"""

from __future__ import annotations

import json
from collections import deque
from datetime import date
from pathlib import Path

from src.config import settings


def parse_licences(*chunks: str | None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for chunk in chunks:
        for part in str(chunk or "").replace("\n", ",").split(","):
            token = part.strip()
            if token and token not in seen:
                seen.add(token)
                out.append(token)
    return out


def is_quota_error(status_code: int, body: str = "") -> bool:
    if status_code == 429:
        return True
    text = str(body or "")
    if "101" in text and ("Licence" in text or "licence" in text or "证书" in text):
        return True
    return "次数" in text and ("超出" in text or "超限" in text or "已超" in text)


class LicencePool:
    """进程内单例队列；状态写入 data/licence_pool.json 按自然日重置。"""

    _shared: LicencePool | None = None

    def __init__(self, licences: list[str], state_path: Path | None = None) -> None:
        self._all = list(licences)
        self._today = date.today().isoformat()
        self._state_path = state_path or (settings.data_dir / "licence_pool.json")
        self._exhausted: set[str] = set()
        self._queue: deque[str] = deque()
        self._load()
        self._rebuild_queue()

    @classmethod
    def shared(cls, licences: list[str] | None = None) -> LicencePool:
        chain = licences or settings.licence_chain
        if cls._shared is None or (licences is not None and list(cls._shared._all) != list(chain)):
            cls._shared = cls(chain)
        return cls._shared

    @classmethod
    def reset_shared(cls) -> None:
        cls._shared = None

    def _load(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if data.get("date") != self._today:
            return
        if data.get("licences") != self._all:
            return
        raw = data.get("exhausted") or []
        self._exhausted = {str(x).strip() for x in raw if str(x).strip()}

    def _save(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "date": self._today,
            "licences": self._all,
            "exhausted": sorted(self._exhausted),
            "queue": list(self._queue),
        }
        self._state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _rebuild_queue(self) -> None:
        self._queue = deque([x for x in self._all if x not in self._exhausted])

    def active(self) -> str:
        return self._queue[0] if self._queue else ""

    def available(self) -> list[str]:
        return list(self._queue)

    def mark_exhausted(self, licence: str) -> str:
        token = (licence or "").strip()
        if token:
            self._exhausted.add(token)
        self._rebuild_queue()
        self._save()
        return self.active()

    def exhausted_today(self) -> bool:
        return not self._queue

    def status(self) -> dict:
        return {
            "active": self.active(),
            "available": self.available(),
            "exhausted_today": sorted(self._exhausted),
            "total": len(self._all),
            "date": self._today,
        }
