from fastapi.testclient import TestClient

from src.main import app
from src.query.presets import PRESET_RESEARCH, PRESET_WATCH, keys_for_preset, WATCH_KEYS


def _headers(client: TestClient) -> dict:
    login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
    token = login.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_watch_preset_is_minimal():
    keys = keys_for_preset(PRESET_WATCH)
    assert keys == list(WATCH_KEYS)
    assert "holders" not in keys
    assert "price" in keys


def test_research_preset_includes_slow_fields():
    keys = keys_for_preset(PRESET_RESEARCH)
    assert "holders" in keys
    assert "low1y" in keys
    assert len(keys) > len(WATCH_KEYS)


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
