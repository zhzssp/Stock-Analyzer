import json
from datetime import date

import pytest

from src.config import settings
from src.market.licence_registry import (
    DEFAULT_CONSUMABLE_SEED,
    LicenceRegistry,
    POOL_CONSUMABLE,
    POOL_RENEWABLE,
)


@pytest.fixture
def reg_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    LicenceRegistry.reset_shared()
    yield tmp_path / "licence_registry.json"
    LicenceRegistry.reset_shared()


def _empty_registry_payload():
    return {
        "preference": {"mode": "auto", "manual_licence": ""},
        "renewable": {"date": date.today().isoformat(), "licences": [], "exhausted": []},
        "consumable": {"licences": []},
    }


def test_auto_schedules_renewable_before_consumable(reg_path):
    reg_path.write_text(json.dumps(_empty_registry_payload()), encoding="utf-8")
    reg = LicenceRegistry(state_path=reg_path, sync_env=False)
    reg.add(POOL_RENEWABLE, "REN-A")
    reg.add(POOL_RENEWABLE, "REN-B")
    reg.add(POOL_CONSUMABLE, "CON-A")
    reg.set_preference("auto", "")
    plan = reg.iteration_plan()
    assert [x[1] for x in plan] == ["REN-A", "REN-B", "CON-A"]


def test_renewable_exhausted_resets_next_day(reg_path):
    reg_path.write_text(json.dumps(_empty_registry_payload()), encoding="utf-8")
    reg = LicenceRegistry(state_path=reg_path, sync_env=False)
    reg.add(POOL_RENEWABLE, "REN-A")
    reg.mark_quota_exhausted("REN-A")
    assert reg.active() == ""
    payload = json.loads(reg_path.read_text(encoding="utf-8"))
    payload["renewable"]["date"] = "2020-01-01"
    reg_path.write_text(json.dumps(payload), encoding="utf-8")
    reg2 = LicenceRegistry(state_path=reg_path, sync_env=False)
    assert reg2.active() == "REN-A"


def test_consumable_removed_when_exhausted(reg_path):
    reg_path.write_text(json.dumps(_empty_registry_payload()), encoding="utf-8")
    reg = LicenceRegistry(state_path=reg_path, sync_env=False)
    reg.add(POOL_CONSUMABLE, "CON-A")
    reg.mark_quota_exhausted("CON-A")
    assert "CON-A" not in reg.status()["consumable"]["licences"]
    assert reg.active() == ""


def test_migrate_includes_consumable_seed(reg_path):
    reg = LicenceRegistry(state_path=reg_path, sync_env=False)
    assert DEFAULT_CONSUMABLE_SEED in reg.status()["consumable"]["licences"]


def test_two_instances_do_not_overwrite_exhausted_marks(reg_path):
    """回归：两个实例各自持内存副本时，不能把对方刚写下的「今日已耗尽」标记覆盖掉。

    旧实现每次 _save 都整份覆盖写且不读回，结果同一张已耗尽的证被反复选中重试，
    每重试一次都要真发一次请求 —— 日志里表现为同一张证当天被判额度用尽十几次。
    """
    reg_path.write_text(json.dumps(_empty_registry_payload()), encoding="utf-8")
    a = LicenceRegistry(state_path=reg_path, sync_env=False)
    a.add(POOL_RENEWABLE, "REN-A")
    a.add(POOL_RENEWABLE, "REN-B")

    b = LicenceRegistry(state_path=reg_path, sync_env=False)  # 第二个实例
    a.mark_quota_exhausted("REN-A")
    b.mark_quota_exhausted("REN-B")  # 旧实现这一步会把 REN-A 的标记抹掉

    fresh = LicenceRegistry(state_path=reg_path, sync_env=False)
    exhausted = fresh.status()["renewable"]["exhausted_today"]
    assert set(exhausted) == {"REN-A", "REN-B"}
    assert fresh.status()["renewable"]["available"] == []
    assert fresh.active() == ""


def test_all_exhausted_today_distinguishes_empty_pool(reg_path):
    """「今天全耗尽」和「压根没配证书」是两回事，不能都报成额度用尽。"""
    reg_path.write_text(json.dumps(_empty_registry_payload()), encoding="utf-8")
    empty = LicenceRegistry(state_path=reg_path, sync_env=False)
    assert empty.all_exhausted_today() is False  # 池是空的，不是用尽

    reg = LicenceRegistry(state_path=reg_path, sync_env=False)
    reg.add(POOL_RENEWABLE, "REN-A")
    assert reg.all_exhausted_today() is False
    reg.mark_quota_exhausted("REN-A")
    assert reg.all_exhausted_today() is True


def test_exhaust_counts_today_flags_repeated_exhaustion(reg_path):
    """同一张证当天被反复判「额度用尽」= 状态被覆盖打穿，必须能被 health 看到。"""
    reg_path.write_text(json.dumps(_empty_registry_payload()), encoding="utf-8")
    reg = LicenceRegistry(state_path=reg_path, sync_env=False)
    reg.add(POOL_RENEWABLE, "REN-A")
    for _ in range(3):
        reg.mark_quota_exhausted("REN-A")
    assert reg.exhaust_counts_today() == {"REN-A…": 3}
    # 计数要能跨实例持久化
    other = LicenceRegistry(state_path=reg_path, sync_env=False)
    assert other.exhaust_counts_today() == {"REN-A…": 3}
