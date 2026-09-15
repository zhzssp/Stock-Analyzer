from fastapi.testclient import TestClient

from src.main import app
from src.platform.bus import bus
from src.tools import registry


def _auth(client: TestClient) -> dict:
    login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_reserved_tools_stay_disabled():
    for tool_id in ("futures_quote", "web_finance_search", "policy_news"):
        spec = registry.get(tool_id)
        assert spec.enabled is False
        assert spec.reason
    assert registry.get("fund_holding").enabled is True
    assert registry.get("export_share").enabled is True


def test_session_followup_uses_history():
    with TestClient(app) as client:
        headers = _auth(client)
        first = client.post("/api/agent/chat", json={"question": "中直股份现价是多少？"}, headers=headers)
        assert first.status_code == 200, first.text
        sid = first.json()["session_id"]
        assert sid
        second = client.post(
            "/api/agent/chat",
            json={"question": "它的研发费用呢？", "session_id": sid},
            headers=headers,
        )
        assert second.status_code == 200, second.text
        assert second.json()["session_id"] == sid
        assert "19.4" in second.json()["answer"]
        listed = client.get("/api/agent/sessions", headers=headers)
        assert listed.status_code == 200
        assert any(s["id"] == sid for s in listed.json())


def test_stream_emits_tool_before_done():
    with TestClient(app) as client:
        headers = _auth(client)
        res = client.post(
            "/api/agent/chat",
            json={"question": "中直股份现价", "stream": True},
            headers=headers,
        )
        assert res.status_code == 200
        assert "text/event-stream" in (res.headers.get("content-type") or "")
        body = res.text
        tool_at = body.find('"type": "tool"')
        done_at = body.find('"type": "done"')
        assert tool_at != -1 and done_at != -1 and tool_at < done_at
        assert "session_id" in body


def test_researcher_skips_missing_news_and_uses_watch():
    with TestClient(app) as client:
        headers = _auth(client)
        chat = client.post(
            "/api/agent/chat",
            json={"question": "看市场：当前和自选相关的市场在发生什么？", "agent": "researcher"},
            headers=headers,
        )
        assert chat.status_code == 200, chat.text
        body = chat.json()
        assert body["agent"] == "researcher"
        ids = {t["id"] for t in body["tools"]}
        assert {"universe", "quote"} <= ids
        assert "web_finance_search" not in ids or any(not t["ok"] for t in body["tools"] if t["id"] == "web_finance_search")


def test_watcher_publishes_bus_and_channels_listed():
    with TestClient(app) as client:
        headers = _auth(client)
        ran = client.post("/api/monitor/run", json={}, headers=headers)
        assert ran.status_code == 200
        health = client.get("/api/health")
        names = {c["id"] for c in health.json()["agent"]["channels"]}
        assert {"log", "desktop", "webhook"} <= names
        topics = {m["topic"] for m in bus.recent()}
        assert "watch.digest" in topics
        listed = client.get("/api/agent/bus?topic=watch.digest")
        assert listed.status_code == 200
        assert listed.json()
