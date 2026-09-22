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
