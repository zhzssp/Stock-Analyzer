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


_LICENCE_WORDS = ("licence", "license", "证书")
_QUOTA_WORDS = ("额度", "次数", "超限", "超出", "已超", "上限", "配额", "用尽")


def is_quota_error(status_code: int, body: str = "") -> bool:
    """当日额度 / 调用次数用尽：命中就该换下一张证书。

    麦蕊的额度提示没有统一格式，见过 `101:Licence…已超限`，也见过只带「额度 / 超限」
    而没有 licence 字样的写法。原写法要求「101 且含 licence/证书」或「次数且含超出/超限」，
    漏掉的组合会让它一直卡在同一张已经用尽的证书上，看起来就是「没有自动切换」。
    宁可多换一张（代价最多一次重试），也不要卡住。
    """
    if status_code == 429:
        return True
    text = str(body or "")
    if not text:
        return False
    lowered = text.lower()
    has_licence = any(k in lowered for k in _LICENCE_WORDS)
    has_quota = any(k in text for k in _QUOTA_WORDS)
    if "101" in text and (has_licence or has_quota):
        return True
    if has_licence and has_quota:
        return True
    # 没有 101 也没有 licence 字样时，只认这几个强特征，避免误判正常响应。
    return any(k in text for k in ("额度已用尽", "当日次数", "调用次数已超", "超出当日", "次数已超"))


def is_licence_unusable(status_code: int, body: str = "") -> bool:
    """证书本身不可用（无效 / 未授权 / 过期）：换下一张，但**不**记为额度用尽。

    额度用尽次日会恢复，证书无效恢复不了——两者不能混为一谈。
    """
    if status_code in (401, 402, 403):
        return True
    text = str(body or "")
    if not text:
        return False
    lowered = text.lower()
    if any(k in lowered for k in _LICENCE_WORDS) and any(
        k in text for k in ("无效", "未授权", "过期", "到期", "禁用", "不存在", "错误")
    ):
        return True
    return False


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
        saved = data.get("licences")
        if saved is not None and list(saved) != list(self._all):
            return
        raw = data.get("exhausted") or []
        self._exhausted = {str(x).strip() for x in raw if str(x).strip()} & set(self._all)

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

    def repair(self) -> bool:
        """Rebuild queue after date roll, config change, or corrupt persisted state."""
        today = date.today().isoformat()
        if self._today != today:
            self._today = today
            self._exhausted.clear()
        self._load()
        self._rebuild_queue()
        if self._queue:
            self._save()
            return True
        if len(self._exhausted) >= len(self._all):
            return False
        # Stale file had queue=[] but not every licence is exhausted — recover.
        self._exhausted = {x for x in self._exhausted if x in self._all}
        self._rebuild_queue()
        if self._queue:
            self._save()
            return True
        return False

    def status(self) -> dict:
        return {
            "active": self.active(),
            "available": self.available(),
            "exhausted_today": sorted(self._exhausted),
            "total": len(self._all),
            "date": self._today,
        }
