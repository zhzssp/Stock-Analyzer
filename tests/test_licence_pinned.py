"""证书「锁定」与「调度」分开后的行为回归。

两条逻辑以前混在同一个 mode 里（auto/renewable/consumable/manual），
现在拆成正交的两件事：
- schedule：不锁定时按什么顺序用池
- pinned：锁定某一张（调度不生效，用完就停在原地，绝不悄悄换证）
"""

import json
from datetime import date

import pytest

from src.config import settings
from src.market.licence_registry import (
    POOL_CONSUMABLE,
    POOL_RENEWABLE,
    LicenceRegistry,
)


def _blank_payload():
    return {
        "preference": {"schedule": "auto", "pinned": ""},
        "renewable": {"date": date.today().isoformat(), "licences": [], "exhausted": []},
        "consumable": {"licences": []},
    }


def _registry(tmp_path, payload=None):
    path = tmp_path / "reg.json"
    path.write_text(json.dumps(payload or _blank_payload()), encoding="utf-8")
    return LicenceRegistry(state_path=path, sync_env=False)


def _tmp():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp())


def test_legacy_manual_mode_migrates_to_pinned():
    """旧 {mode: manual, manual_licence: X} 要迁移成 {pinned: X}，老配置不能丢。"""
    from src.market.licence_registry import _normalize_preference

    assert _normalize_preference({"mode": "manual", "manual_licence": "KEY-A"}) == {
        "schedule": "auto",
        "pinned": "KEY-A",
    }
    assert _normalize_preference({"mode": "consumable"}) == {"schedule": "consumable", "pinned": ""}
    assert _normalize_preference({"mode": "auto", "manual_licence": "IGNORED"}) == {
        "schedule": "auto",
        "pinned": "",
    }

    # 端到端：读一份旧格式的状态文件，锁定关系要还在
    payload = _blank_payload()
    payload["preference"] = {"mode": "manual", "manual_licence": "KEY-A"}
    path = _tmp() / "reg.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    reg = LicenceRegistry(state_path=path, sync_env=False)
    reg.add(POOL_RENEWABLE, "KEY-A")
    assert reg.pinned_licence() == "KEY-A"
    assert [c[1] for c in reg.iteration_plan()] == ["KEY-A"]


def test_pinned_licence_is_the_only_candidate():
    reg = _registry(_tmp())
    reg.add(POOL_RENEWABLE, "KEY-A")
    reg.add(POOL_RENEWABLE, "KEY-B")
    reg.set_preference("auto", "KEY-B")

    assert reg.pinned_licence() == "KEY-B"
    assert [c[1] for c in reg.iteration_plan()] == ["KEY-B"], "锁定后不能再用别的证"


def test_pinned_exhausted_today_yields_nothing_and_stays_pinned():
    """锁定证当天用尽：交不出证（由调用方明确报错），且**不能**悄悄退回调度。"""
    reg = _registry(_tmp())
    reg.add(POOL_RENEWABLE, "KEY-A")
    reg.add(POOL_RENEWABLE, "KEY-B")
    reg.set_preference("auto", "KEY-A")

    reg.mark_quota_exhausted("KEY-A")

    assert reg.iteration_plan() == [], "已用尽的锁定证不能再被派出去打请求"
    assert reg.pinned_licence() == "KEY-A", "锁定状态必须保持，不能静默解锁"
    assert reg.pinned_state()["exhausted_today"] is True


def test_pinned_consumable_removed_keeps_pinned_flag():
    """用完就没的那类被移除后：仍保持锁定，好让报错说清「你锁定的这张已用完」。"""
    reg = _registry(_tmp())
    reg.add(POOL_CONSUMABLE, "KEY-C")
    reg.set_preference("auto", "KEY-C")

    reg.mark_quota_exhausted("KEY-C")

    assert "KEY-C" not in reg.status()["consumable"]["licences"]
    assert reg.pinned_licence() == "KEY-C", "被用完移除 ≠ 用户主动删除，不能自动解锁"
    assert reg.pinned_state()["in_pool"] is False
    assert reg.iteration_plan() == []


def test_user_removing_pinned_licence_unlocks():
    """用户在界面上主动删掉锁定的那张 → 视为解除锁定（意图明确）。"""
    reg = _registry(_tmp())
    reg.add(POOL_RENEWABLE, "KEY-A")
    reg.add(POOL_RENEWABLE, "KEY-B")
    reg.set_preference("auto", "KEY-A")

    reg.remove(POOL_RENEWABLE, "KEY-A")

    assert reg.pinned_licence() == ""
    assert [c[1] for c in reg.iteration_plan()] == ["KEY-B"], "解锁后应回到正常调度"


def test_pinning_unknown_licence_adds_it_as_renewable():
    """锁定一张不在池里的证：按「每天会恢复」入池（这类用尽不会把证弄丢）。"""
    reg = _registry(_tmp())
    reg.set_preference("auto", "NEW-KEY")

    assert "NEW-KEY" in reg.status()["renewable"]["licences"]
    assert [c[1] for c in reg.iteration_plan()] == ["NEW-KEY"]


def test_schedule_mode_choices():
    reg = _registry(_tmp())
    reg.add(POOL_RENEWABLE, "KEY-A")
    reg.add(POOL_CONSUMABLE, "KEY-C")

    reg.set_preference("auto", "")
    assert [c[1] for c in reg.iteration_plan()] == ["KEY-A", "KEY-C"]

    reg.set_preference("renewable", "")
    assert [c[1] for c in reg.iteration_plan()] == ["KEY-A"]

    reg.set_preference("consumable", "")
    assert [c[1] for c in reg.iteration_plan()] == ["KEY-C"]


def test_unknown_schedule_is_rejected():
    reg = _registry(_tmp())
    with pytest.raises(ValueError):
        reg.set_preference("manual", "KEY-A")  # manual 不再是调度模式


def test_demo_licence_cannot_be_added_or_pinned():
    reg = _registry(_tmp())
    with pytest.raises(ValueError):
        reg.add(POOL_RENEWABLE, settings.demo_licence)
    with pytest.raises(ValueError):
        reg.set_preference("auto", settings.demo_licence)


def test_status_exposes_schedule_and_pinned():
    reg = _registry(_tmp())
    reg.add(POOL_RENEWABLE, "KEY-A")
    reg.set_preference("renewable", "KEY-A")
    st = reg.status()
    assert st["schedule"] == "renewable"
    assert st["pinned"] == "KEY-A"
    assert st["pinned_state"]["in_pool"] is True
