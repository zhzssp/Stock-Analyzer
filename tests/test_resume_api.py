"""刷新行情带 resume 时，同一页第二次只补还没生效的代码，并按原顺序返回。"""

import json
from datetime import datetime

from fastapi.testclient import TestClient

from src.main import app
from src.query.resume_window import SH


def _login(client):
    login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def _done(text: str) -> dict:
    found = {}
    for block in text.split("\n\n"):
        event = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data += line.split(":", 1)[1].strip()
        if event == "done" and data:
            found = json.loads(data)
    return found


def test_quote_resume_skips_codes_that_are_still_valid(tmp_path, monkeypatch):
    moment = datetime(2026, 10, 29, 10, 0, tzinfo=SH)
    monkeypatch.setattr("src.query.resume_window.now_shanghai", lambda: moment)
    monkeypatch.setattr("src.query.resume_ledger.ledger_dir", lambda: tmp_path)
    body = {
        "codes": ["600519", "000001"],
        "pool": "exchange:sh",
        "fields": ["price", "pct", "name"],
        "refresh_mode": "quote",
        "resume": True,
        "limit": 2,
    }
    with TestClient(app) as client:
        headers = _login(client)
        first = client.post("/api/query/stream", json=body, headers=headers)
        assert first.status_code == 200, first.text
        first_done = _done(first.text)
        assert first_done["resume"]["used"] is False
        assert first_done["resume"]["refetched"] == 2
        assert first_done["code_order"] == ["600519", "000001"]
        second = client.post("/api/query/stream", json=body, headers=headers)
        assert second.status_code == 200, second.text
        second_done = _done(second.text)
        assert second_done["resume"]["used"] is True
        assert second_done["resume"]["skipped"] == 2
        assert second_done["resume"]["refetched"] == 0
        assert second_done["code_order"] == first_done["code_order"]
        view = client.get("/api/query/resume", params={"mode": "quote", "pool": "exchange:sh"}, headers=headers)
        assert view.status_code == 200, view.text
        body_json = view.json()
        assert body_json["status"] == "open"
        assert body_json["resume_from"] == 0
        assert body_json["quoted"] >= 1
        assert body_json["remaining"] >= 1
    assert list(tmp_path.rglob("quote.json"))
    assert not list(tmp_path.rglob("full.json"))


def test_cache_query_does_not_write_the_resume_ledger(tmp_path, monkeypatch):
    monkeypatch.setattr("src.query.resume_ledger.ledger_dir", lambda: tmp_path)
    body = {
        "codes": ["600519"],
        "fields": ["price", "industry"],
        "refresh_mode": "cache",
        "resume": True,
        "limit": 1,
    }
    with TestClient(app) as client:
        headers = _login(client)
        res = client.post("/api/query/stream", json=body, headers=headers)
        assert res.status_code == 200, res.text
        assert "resume" not in _done(res.text)
    assert not list(tmp_path.rglob("*.json"))
