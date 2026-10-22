from fastapi.testclient import TestClient

from src.main import app
from src.query.presets import (
    PRESET_RESEARCH,
    PRESET_WATCH,
    RESEARCH_KEYS,
    WATCH_KEYS,
    default_for_new_user,
    keys_for_preset,
)
from src.query.registry import registry


def _headers(client: TestClient) -> dict:
    login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
    token = login.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_watch_preset_is_minimal():
    keys = keys_for_preset(PRESET_WATCH)
    assert keys == list(WATCH_KEYS)
    assert "holders" not in keys
    assert "price" in keys


def test_default_checked_fields_are_the_seventeen():
    preset, keys = default_for_new_user()
    assert preset == PRESET_RESEARCH
    assert keys == list(RESEARCH_KEYS)


def test_research_preset_is_the_core_sheet():
    keys = keys_for_preset(PRESET_RESEARCH)
    assert keys == list(RESEARCH_KEYS)
    assert keys == registry.default_keys()
    assert keys[:4] == ["name", "code", "price", "pct"]
    assert keys[-1] == "pb"
    for dropped in ("sector", "sw_l1", "hot_concepts", "top_holders", "yffy", "flow_net", "low1y", "target"):
        assert dropped not in keys


def test_api_prefs_preset():
    with TestClient(app) as client:
        headers = _headers(client)
        data = client.get("/api/query/prefs", headers=headers).json()
        assert data["preset"] in ("watch", "research", "custom")
        assert data.get("presets")
        put = client.put(
            "/api/query/prefs",
            json={"preset": "watch", "fields": []},
            headers=headers,
        )
        assert put.status_code == 200
        assert put.json()["fields"] == list(WATCH_KEYS)
        restored = client.put(
            "/api/query/prefs",
            json={"preset": "research", "fields": []},
            headers=headers,
        )
        assert restored.status_code == 200
        assert restored.json()["fields"] == list(RESEARCH_KEYS)
