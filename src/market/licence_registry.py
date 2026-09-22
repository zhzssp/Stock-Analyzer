"""双证书池：每日刷新额度池 + 用尽即移除的长期池。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from src.config import settings
from src.market.licence_pool import parse_licences

PoolKind = Literal["renewable", "consumable"]
ScheduleMode = Literal["auto", "renewable", "consumable", "manual"]

POOL_RENEWABLE: PoolKind = "renewable"
POOL_CONSUMABLE: PoolKind = "consumable"

DEFAULT_CONSUMABLE_SEED = "9EC8F5FE-BF7C-40DA-8B0B-FE9E50ADEE2F"


class LicenceRegistry:
    """renewable：当日 101/429 后换下一张，次日自动恢复。consumable：超限后从池中删除。"""

    _shared: LicenceRegistry | None = None

    def __init__(self, state_path: Path | None = None, sync_env: bool = True) -> None:
        self._path = state_path or (settings.data_dir / "licence_registry.json")
        self._sync_env = sync_env
        self._today = date.today().isoformat()
        self._renewable: list[str] = []
        self._exhausted: set[str] = set()
        self._consumable: list[str] = []
        self._preference: dict = {"mode": "auto", "manual_licence": ""}
        self._load_or_migrate()
        if self._sync_env:
            self._sync_env_renewable()
        self._roll_day_if_needed()
        self._save()

    @classmethod
    def shared(cls) -> LicenceRegistry:
        if cls._shared is None:
            cls._shared = cls()
        return cls._shared

    @classmethod
    def reset_shared(cls) -> None:
        cls._shared = None

    def has_any_licence(self) -> bool:
        return bool(self._renewable or self._consumable)

    def pool_of(self, licence: str) -> PoolKind | None:
        token = (licence or "").strip()
        if not token:
            return None
        if token in self._renewable:
            return POOL_RENEWABLE
        if token in self._consumable:
            return POOL_CONSUMABLE
        return None

    def _roll_day_if_needed(self) -> None:
        today = date.today().isoformat()
        if self._today != today:
            self._today = today
            self._exhausted.clear()

    def _sync_env_renewable(self) -> None:
        for lic in settings.licence_chain:
            if lic in self._renewable or lic in self._consumable:
                continue
            self._renewable.append(lic)

    def _load_or_migrate(self) -> None:
        if self._path.exists():
            try:
                data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            if data:
                self._apply_payload(data)
                return
        self._migrate_legacy()
        if DEFAULT_CONSUMABLE_SEED not in self._consumable and DEFAULT_CONSUMABLE_SEED not in self._renewable:
            self._consumable.append(DEFAULT_CONSUMABLE_SEED)

    def _migrate_legacy(self) -> None:
        legacy = settings.data_dir / "licence_pool.json"
        self._renewable = list(settings.licence_chain)
        self._exhausted = set()
        self._consumable = []
        if legacy.exists():
            try:
                old = json.loads(legacy.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                old = {}
            saved = old.get("licences")
            if isinstance(saved, list) and saved:
                self._renewable = parse_licences(*(str(x) for x in saved))
            if old.get("date") == self._today:
                raw = old.get("exhausted") or []
                self._exhausted = {str(x).strip() for x in raw if str(x).strip()} & set(self._renewable)

    def _apply_payload(self, data: dict) -> None:
        pref = data.get("preference") or {}
        mode = str(pref.get("mode") or "auto").strip().lower()
        if mode not in ("auto", "renewable", "consumable", "manual"):
            mode = "auto"
        self._preference = {
            "mode": mode,
            "manual_licence": str(pref.get("manual_licence") or "").strip(),
        }
        ren = data.get("renewable") or {}
        self._renewable = [str(x).strip() for x in (ren.get("licences") or []) if str(x).strip()]
        if ren.get("date") == self._today:
            raw = ren.get("exhausted") or []
            self._exhausted = {str(x).strip() for x in raw if str(x).strip()} & set(self._renewable)
        else:
            self._exhausted = set()
        self._today = str(ren.get("date") or self._today)
        cons = data.get("consumable") or {}
        self._consumable = [str(x).strip() for x in (cons.get("licences") or []) if str(x).strip()]

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "preference": self._preference,
            "renewable": {
                "date": self._today,
                "licences": self._renewable,
                "exhausted": sorted(self._exhausted),
            },
            "consumable": {"licences": self._consumable},
        }
        self._path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def renewable_available(self) -> list[str]:
        self._roll_day_if_needed()
        return [x for x in self._renewable if x not in self._exhausted]

    def consumable_available(self) -> list[str]:
        return list(self._consumable)

    def iteration_plan(self) -> list[tuple[PoolKind, str]]:
        mode = self._preference.get("mode") or "auto"
        manual = (self._preference.get("manual_licence") or "").strip()
        if mode == "manual":
            kind = self.pool_of(manual)
            return [(kind, manual)] if kind else []
        renewable = [(POOL_RENEWABLE, x) for x in self.renewable_available()]
        consumable = [(POOL_CONSUMABLE, x) for x in self.consumable_available()]
        if mode == "renewable":
            return renewable
        if mode == "consumable":
            return consumable
        return renewable + consumable

    def active(self) -> str:
        plan = self.iteration_plan()
        return plan[0][1] if plan else ""

    def active_pool(self) -> PoolKind | "":
        plan = self.iteration_plan()
        return plan[0][0] if plan else ""

    def mark_quota_exhausted(self, licence: str) -> str:
        token = (licence or "").strip()
        if not token:
            return self.active()
        if token in self._renewable:
            self._exhausted.add(token)
        elif token in self._consumable:
            self._consumable = [x for x in self._consumable if x != token]
            manual = (self._preference.get("manual_licence") or "").strip()
            if manual == token:
                self._preference["manual_licence"] = ""
        self._save()
        return self.active()

    def repair(self) -> bool:
        self._roll_day_if_needed()
        if self._sync_env:
            self._sync_env_renewable()
        if self.iteration_plan():
            self._save()
            return True
        stale = {x for x in self._exhausted if x not in self._renewable}
        if stale:
            self._exhausted -= stale
        if self.iteration_plan():
            self._save()
            return True
        return bool(self.iteration_plan())

    def add(self, pool: str, licence: str) -> None:
        token = (licence or "").strip()
        if not token:
            raise ValueError("证书不能为空")
        kind = pool.strip().lower()
        if kind not in (POOL_RENEWABLE, POOL_CONSUMABLE):
            raise ValueError("未知池类型")
        other = POOL_CONSUMABLE if kind == POOL_RENEWABLE else POOL_RENEWABLE
        if self.pool_of(token) == other:
            self.remove(other, token)
        if kind == POOL_RENEWABLE:
            if token not in self._renewable:
                self._renewable.append(token)
            self._exhausted.discard(token)
        else:
            if token not in self._consumable:
                self._consumable.append(token)
        self._save()

    def remove(self, pool: str, licence: str) -> None:
        token = (licence or "").strip()
        kind = pool.strip().lower()
        if kind == POOL_RENEWABLE:
            self._renewable = [x for x in self._renewable if x != token]
            self._exhausted.discard(token)
        elif kind == POOL_CONSUMABLE:
            self._consumable = [x for x in self._consumable if x != token]
        else:
            raise ValueError("未知池类型")
        manual = (self._preference.get("manual_licence") or "").strip()
        if manual == token:
            self._preference["manual_licence"] = ""
        self._save()

    def set_preference(self, mode: str, manual_licence: str = "") -> None:
        m = (mode or "auto").strip().lower()
        if m not in ("auto", "renewable", "consumable", "manual"):
            raise ValueError("未知调度模式")
        manual = (manual_licence or "").strip()
        if m == "manual" and manual and not self.pool_of(manual):
            raise ValueError("指定证书不在任一池中")
        self._preference = {"mode": m, "manual_licence": manual}
        self._save()

    def status(self) -> dict:
        self._roll_day_if_needed()
        return {
            "preference": dict(self._preference),
            "active": self.active(),
            "active_pool": self.active_pool(),
            "renewable": {
                "label": "每日刷新额度",
                "description": "当日用尽后自动换下一张，次日额度恢复，可循环使用",
                "licences": list(self._renewable),
                "available": self.renewable_available(),
                "exhausted_today": sorted(self._exhausted),
                "total": len(self._renewable),
                "date": self._today,
            },
            "consumable": {
                "label": "长期额度（用尽即移除）",
                "description": "不限每日次数，总额度耗尽后从池中删除该证书",
                "licences": list(self._consumable),
                "available": self.consumable_available(),
                "total": len(self._consumable),
            },
        }

    def legacy_renewable_status(self) -> dict | None:
        """兼容旧 health.licence_pool 字段。"""
        st = self.status()
        ren = st["renewable"]
        return {
            "active": st["active"] if st["active_pool"] == POOL_RENEWABLE else (ren["available"][0] if ren["available"] else ""),
            "available": ren["available"],
            "exhausted_today": ren["exhausted_today"],
            "total": ren["total"],
            "date": ren["date"],
        }
