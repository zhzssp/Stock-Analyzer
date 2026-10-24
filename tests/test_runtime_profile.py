import json

from fastapi.testclient import TestClient

from src.config import settings
from src.main import app
from src.platform import cache_memory, runtime_profile as rp


def test_auto_follows_ram():
    gib = 1024**3
    assert rp.resolve_mode("auto", 8 * gib) == "lite"
    assert rp.resolve_mode("auto", 8 * gib + 1) == "full"
    assert rp.resolve_mode("auto", None) == "full"
    assert rp.resolve_mode("full", 4 * gib) == "full"
    assert rp.resolve_mode("lite", 32 * gib) == "lite"
    assert rp.resolve_mode("nope", 32 * gib) == "full"


def test_lite_shrinks_caps_and_cache_then_restores(tmp_path, monkeypatch):
    rp.reset_for_tests()
    monkeypatch.setattr(settings, "cache_memory_enabled", True)
    monkeypatch.setattr(settings, "cache_memory_max_mb", 40)
    monkeypatch.setattr(settings, "query_workers", 6)
    sample = tmp_path / "sample.json"
    sample.write_text("{}", encoding="utf-8")
    cache_memory.clear()
    cache_memory.put(str(sample), {"name": "缓存"})
    assert cache_memory.stats()["entries"] == 1
    try:
        lite = rp.apply("lite", persist=False)
        assert lite["resolved"] == "lite"
        assert lite["agents_enabled"] is False
        assert settings.cache_memory_max_mb == 16
        assert settings.query_workers == 2
        assert cache_memory.stats()["entries"] == 0

        full = rp.apply("full", persist=False)
        assert full["resolved"] == "full"
        assert full["agents_enabled"] is True
        assert settings.cache_memory_max_mb == 40
        assert settings.query_workers == 6
    finally:
        cache_memory.clear()
        rp.reset_for_tests()


def test_lite_keeps_query_and_blocks_agent(tmp_path, monkeypatch):
    rp.reset_for_tests()
    monkeypatch.setattr(settings, "runtime_profile", "")
    monkeypatch.setattr(rp, "profile_path", lambda: tmp_path / "runtime_profile.json")
    try:
        with TestClient(app) as client:
            login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
            assert login.status_code == 200, login.text
            headers = {"Authorization": f"Bearer {login.json()['token']}"}

            switched = client.post("/api/runtime", json={"mode": "lite"}, headers=headers)
            assert switched.status_code == 200, switched.text
            assert switched.json()["resolved"] == "lite"
            assert switched.json()["agents_enabled"] is False
            saved = json.loads((tmp_path / "runtime_profile.json").read_text(encoding="utf-8"))
            assert saved["mode"] == "lite"

            query = client.post("/api/query/run", json={"codes": ["600519"]}, headers=headers)
            assert query.status_code == 200, query.text
            assert query.json()["rows"][0]["name"]

            chat = client.post("/api/agent/chat", json={"question": "茅台现价"}, headers=headers)
            assert chat.status_code == 409
            assert "轻量" in chat.json()["detail"]

            scan = client.post("/api/monitor/run", headers=headers)
            assert scan.status_code == 409

            health = client.get("/api/health")
            assert health.json()["runtime"]["resolved"] == "lite"
            assert health.json()["agent"]["enabled"] is False
            assert "llm_status" in health.json()["agent"]

            back = client.post("/api/runtime", json={"mode": "full"}, headers=headers)
            assert back.status_code == 200
            assert back.json()["agents_enabled"] is True
    finally:
        rp.reset_for_tests()


def test_env_locks_the_switch(monkeypatch):
    rp.reset_for_tests()
    monkeypatch.setattr(settings, "runtime_profile", "full")
    try:
        with TestClient(app) as client:
            login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
            headers = {"Authorization": f"Bearer {login.json()['token']}"}
            locked = client.post("/api/runtime", json={"mode": "lite"}, headers=headers)
            assert locked.status_code == 409
            assert rp.agents_enabled() is True
    finally:
        rp.reset_for_tests()
