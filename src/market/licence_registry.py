"""双证书池：每日刷新额度池 + 用尽即移除的长期池。"""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from datetime import date
from pathlib import Path
from typing import Literal

from src.config import settings
from src.market.licence_pool import parse_licences

PoolKind = Literal["renewable", "consumable"]
ScheduleMode = Literal["auto", "renewable", "consumable", "manual"]

POOL_RENEWABLE: PoolKind = "renewable"
POOL_CONSUMABLE: PoolKind = "consumable"

# 进程内串行（同一进程里查询是并发的）。跨进程靠 _file_lock。
_PROCESS_LOCK = threading.Lock()

DEFAULT_CONSUMABLE_SEED = "9EC8F5FE-BF7C-40DA-8B0B-FE9E50ADEE2F"


SCHEDULE_MODES = ("auto", "renewable", "consumable")


def _normalize_preference(pref: dict | None) -> dict:
    """把偏好统一成 {schedule, pinned}。

    旧格式是 {mode, manual_licence}：把「换不换」和「怎么换」混在一个字段里 ——
    mode=manual 其实是「锁定某一张」，和 auto/renewable/consumable（池调度）不是同一维度。
    这里做迁移，老用户的配置不会丢。
    """
    pref = pref or {}
    schedule = str(pref.get("schedule") or "").strip().lower()
    pinned = str(pref.get("pinned") or "").strip()
    if not schedule:
        mode = str(pref.get("mode") or "auto").strip().lower()
        if mode == "manual":
            # 旧「指定证书」= 锁定这张；调度偏好沿用默认
            schedule = "auto"
            pinned = pinned or str(pref.get("manual_licence") or "").strip()
        elif mode in SCHEDULE_MODES:
            schedule = mode
        else:
            schedule = "auto"
    if schedule not in SCHEDULE_MODES:
        schedule = "auto"
    return {"schedule": schedule, "pinned": pinned}


class LicenceRegistry:
    """renewable：当日 101/429 后换下一张，次日自动恢复。consumable：超限后从池中删除。

    两件事分开管：
    - schedule：不锁定时按什么顺序用池（auto / renewable / consumable）
    - pinned：锁定某一张（非空时调度不生效，用完就停在原地报错，不悄悄换）
    """

    _shared: LicenceRegistry | None = None

    # 拿不到锁时的最长等待；陈旧锁（进程被强杀残留）多久后可以被清掉。
    _lock_timeout_sec = 5.0
    _stale_lock_sec = 30.0

    def __init__(self, state_path: Path | None = None, sync_env: bool = True) -> None:
        self._path = state_path or (settings.data_dir / "licence_registry.json")
        self._sync_env = sync_env
        self._today = date.today().isoformat()
        self._renewable: list[str] = []
        self._exhausted: set[str] = set()
        self._consumable: list[str] = []
        # 当天每张证被判「额度用尽」的次数。同一张证反复出现 = 状态被覆盖打穿，需要立刻发现。
        self._exhaust_counts: dict[str, int] = {}
        self._counts_date = self._today
        self._preference: dict = {"schedule": "auto", "pinned": ""}
        self._disk_stamp: tuple | None = None
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
        self._maybe_reload()
        return bool(self._renewable or self._consumable)

    def pool_of(self, licence: str) -> PoolKind | None:
        token = (licence or "").strip()
        if not token:
            return None
        self._maybe_reload()
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
        self._preference = _normalize_preference(data.get("preference"))
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
        counts = data.get("exhaust_counts") or {}
        self._counts_date = str(counts.get("date") or self._today)
        if self._counts_date == self._today and isinstance(counts.get("counts"), dict):
            self._exhaust_counts = {str(k): int(v) for k, v in counts["counts"].items()}
        else:
            self._exhaust_counts = {}
            self._counts_date = self._today

    # ---- 并发安全：文件锁 + 读-改-写 + 原子替换 ----
    # 之前多个实例各自持一份内存副本、每次 _save 都整份覆盖写，
    # 结果是「某张证今天已耗尽」的标记会被别的进程抹掉，同一张废证被反复重试，
    # 每重试一次都要真发一次请求，额度就是这么烧掉的（见 data/logs/licence.log）。

    def _stamp(self) -> tuple:
        try:
            st = self._path.stat()
        except OSError:
            return ()
        return (st.st_mtime_ns, st.st_size)

    def _lock_path(self) -> Path:
        return self._path.with_name(self._path.name + ".lock")

    @contextlib.contextmanager
    def _file_lock(self):
        """跨进程互斥：独占创建锁文件。拿不到锁最多等 _lock_timeout_sec，超时也不卡死。"""
        lock = self._lock_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + self._lock_timeout_sec
        fd = None
        while True:
            try:
                fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                # 进程被强杀会留下锁文件，超过陈旧阈值就清掉
                try:
                    if time.time() - os.path.getmtime(str(lock)) > self._stale_lock_sec:
                        os.unlink(str(lock))
                        continue
                except OSError:
                    pass
                if time.monotonic() >= deadline:
                    break
                time.sleep(0.02)
        try:
            if fd is not None:
                os.write(fd, str(os.getpid()).encode("utf-8"))
            yield
        finally:
            if fd is not None:
                os.close(fd)
            with contextlib.suppress(OSError):
                os.unlink(str(lock))

    def _reload_from_disk(self) -> None:
        """改动前先读回别的进程刚写入的状态，避免用旧副本覆盖。"""
        stamp = self._stamp()
        if stamp == self._disk_stamp:
            return
        self._disk_stamp = stamp
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return
        if data:
            self._apply_payload(data)

    def _maybe_reload(self) -> None:
        """读操作也先看一眼文件有没有被别的进程改过。"""
        if self._stamp() != self._disk_stamp:
            with _PROCESS_LOCK:
                self._reload_from_disk()

    @contextlib.contextmanager
    def _transaction(self):
        """所有写操作都走这里：加锁 → 重新读 → 改（yield 内）→ 原子写回。"""
        with _PROCESS_LOCK:
            with self._file_lock():
                self._reload_from_disk()
                yield
                self._save_locked()

    def _save(self) -> None:
        """持久化当前内存状态（初始化用，不会读回覆盖自己刚 migrate 出来的内容）。"""
        with _PROCESS_LOCK:
            with self._file_lock():
                self._save_locked()

    def _save_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "preference": self._preference,
            "renewable": {
                "date": self._today,
                "licences": self._renewable,
                "exhausted": sorted(self._exhausted),
            },
            "consumable": {"licences": self._consumable},
            "exhaust_counts": {"date": self._counts_date, "counts": self._exhaust_counts},
        }
        # 原子替换：别的进程要么读到旧文件要么读到新文件，不会读到写了一半的。
        tmp = self._path.with_name(f"{self._path.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(self._path))
        self._disk_stamp = self._stamp()

    def renewable_available(self) -> list[str]:
        self._maybe_reload()
        self._roll_day_if_needed()
        return [x for x in self._renewable if x not in self._exhausted]

    def consumable_available(self) -> list[str]:
        self._maybe_reload()
        return list(self._consumable)

    def pinned_licence(self) -> str:
        """当前锁定的证书（空 = 不锁定，走调度）。"""
        self._maybe_reload()
        return str(self._preference.get("pinned") or "").strip()

    def schedule_mode(self) -> str:
        self._maybe_reload()
        return str(self._preference.get("schedule") or "auto").strip().lower()

    def pinned_state(self) -> dict:
        """锁定证的当前状况，给界面与报错用：还在不在池里、是不是当天用尽了。

        刻意不做 _maybe_reload()：这个方法在每次取数时都会被调用（_get 里判断锁定证是否可用），
        放在热路径上会每次都去 stat / 读文件。调用方 iteration_plan() 已经保证状态是新的。
        """
        self._roll_day_if_needed()
        token = str(self._preference.get("pinned") or "").strip()
        if not token:
            return {"pinned": "", "in_pool": False, "pool": None, "exhausted_today": False}
        kind = self.pool_of(token)
        return {
            "pinned": token,
            "in_pool": kind is not None,
            "pool": kind,
            "exhausted_today": bool(kind == POOL_RENEWABLE and token in self._exhausted),
        }

    def iteration_plan(self) -> list[tuple[PoolKind, str]]:
        self._maybe_reload()
        pinned = self.pinned_licence()
        if pinned:
            # 锁定是硬约束：目标不在池里、或当天已判用尽，就直接交不出证
            # （由调用方明确报错，绝不能悄悄退回调度去用别的证）。
            kind = self.pool_of(pinned)
            if kind is None:
                return []
            if kind == POOL_RENEWABLE and pinned in self._exhausted:
                return []
            return [(kind, pinned)]
        schedule = self.schedule_mode()
        renewable = [(POOL_RENEWABLE, x) for x in self.renewable_available()]
        consumable = [(POOL_CONSUMABLE, x) for x in self.consumable_available()]
        if schedule == "renewable":
            return renewable
        if schedule == "consumable":
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
        with self._transaction():
            if token in self._renewable:
                self._exhausted.add(token)
            elif token in self._consumable:
                self._consumable = [x for x in self._consumable if x != token]
                # 这里**不清** pinned：证是被「用完」弄没的，不是用户删的。
                # 保持锁定，让调用方明确报「你锁定的这张已用完并从池中移除」，
                # 而不是悄悄退回调度去用别的证。
            self._bump_exhaust_count(token)
        return self.active()

    def _bump_exhaust_count(self, token: str) -> None:
        """记「同一张证今天被判额度用尽」的次数。同一张反复出现 = 状态被覆盖，需要立刻发现。"""
        self._roll_day_if_needed()
        if self._counts_date != self._today:
            self._counts_date = self._today
            self._exhaust_counts = {}
        self._exhaust_counts[token] = int(self._exhaust_counts.get(token, 0)) + 1

    def exhaust_counts_today(self) -> dict[str, int]:
        """给 health 用：{证书前8位…: 当天被判额度用尽的次数}。"""
        self._maybe_reload()
        self._roll_day_if_needed()
        if self._counts_date != self._today:
            return {}
        return {k[:8] + "…": v for k, v in sorted(self._exhaust_counts.items(), key=lambda kv: -kv[1])}

    def all_exhausted_today(self) -> bool:
        """池里还有证，但今天一张都派不出来 —— 与「压根没配证书」是两回事。"""
        self._maybe_reload()
        self._roll_day_if_needed()
        return bool(self._renewable or self._consumable) and not self.iteration_plan()

    def repair(self) -> bool:
        with self._transaction():
            self._roll_day_if_needed()
            if self._sync_env:
                self._sync_env_renewable()
            if self.iteration_plan():
                return True
            stale = {x for x in self._exhausted if x not in self._renewable}
            if stale:
                self._exhausted -= stale
            return bool(self.iteration_plan())

    def _add_locked(self, kind: str, token: str) -> None:
        """add 的无锁版本：给 add() 与 set_preference() 在事务内调用。"""
        other = POOL_CONSUMABLE if kind == POOL_RENEWABLE else POOL_RENEWABLE
        if self.pool_of(token) == other:
            self._remove_locked(other, token)
        if kind == POOL_RENEWABLE:
            if token not in self._renewable:
                self._renewable.append(token)
            self._exhausted.discard(token)
        else:
            if token not in self._consumable:
                self._consumable.append(token)

    def add(self, pool: str, licence: str) -> None:
        token = (licence or "").strip()
        if not token:
            raise ValueError("证书不能为空")
        if token == settings.demo_licence:
            raise ValueError("演示证不能加入证书池：它只会返回样本数据")
        kind = pool.strip().lower()
        if kind not in (POOL_RENEWABLE, POOL_CONSUMABLE):
            raise ValueError("未知池类型")
        with self._transaction():
            self._add_locked(kind, token)

    def _remove_locked(self, kind: str, token: str) -> None:
        """remove 的无锁版本：给 add() 在事务内调用，避免嵌套加锁。"""
        if kind == POOL_RENEWABLE:
            self._renewable = [x for x in self._renewable if x != token]
            self._exhausted.discard(token)
        elif kind == POOL_CONSUMABLE:
            self._consumable = [x for x in self._consumable if x != token]
        else:
            raise ValueError("未知池类型")
        # 用户主动删掉锁定的这张 → 视为解除锁定（意图明确）。
        # 若是「用完被移除」（mark_quota_exhausted），那里不动 pinned，好让报错说清楚。
        if self._preference.get("pinned") == token:
            self._preference["pinned"] = ""

    def remove(self, pool: str, licence: str) -> None:
        token = (licence or "").strip()
        kind = pool.strip().lower()
        with self._transaction():
            self._remove_locked(kind, token)

    def set_preference(self, schedule: str = "auto", pinned: str = "") -> None:
        """schedule=auto|renewable|consumable；pinned 非空 = 锁定这张（调度不生效）。"""
        s = (schedule or "auto").strip().lower()
        if s not in SCHEDULE_MODES:
            raise ValueError("未知调度模式")
        token = (pinned or "").strip()
        if token and token == settings.demo_licence:
            raise ValueError("不能锁定演示证：它只会返回样本数据")
        with self._transaction():
            if token and self.pool_of(token) is None:
                # 锁定的证不在池里：按「每天会恢复」入池 —— 这类用尽只是当天不可用，
                # 不会像「用完就没」那样把证弄丢。
                self._add_locked(POOL_RENEWABLE, token)
            self._preference = {"schedule": s, "pinned": token}

    def status(self) -> dict:
        self._maybe_reload()
        self._roll_day_if_needed()
        return {
            "preference": dict(self._preference),
            "schedule": self.schedule_mode(),
            "pinned": self.pinned_licence(),
            "pinned_state": self.pinned_state(),
            "active": self.active(),
            "active_pool": self.active_pool(),
            "all_exhausted_today": self.all_exhausted_today(),
            "exhaust_counts_today": self.exhaust_counts_today(),
            "renewable": {
                "label": "每日刷新额度",
                "description": "当日用尽后自动换下一张，次日额度恢复，可循环使用",
                "licences": list(self._renewable),
                "available": self.renewable_available(),
                "exhausted_today": sorted(self._exhausted),
                "exhaust_counts": {k[:8] + "…": self._exhaust_counts.get(k, 0) for k in self._renewable if self._exhaust_counts.get(k)},
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
