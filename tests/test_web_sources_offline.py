from fastapi.testclient import TestClient

from src.db import SessionLocal
from src.main import app
from src.models import Alert, User
from src.platform.web_sources import (
    Document,
    check_url,
    match_item,
    parse_items,
    watch_needles,
)


def _auth(client: TestClient) -> dict:
    login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_check_url_rejects_lan_and_file():
    try:
        check_url("file:///etc/passwd")
        assert False
    except ValueError:
        pass
    try:
        check_url("http://127.0.0.1/x")
        assert False
    except ValueError:
        pass
    try:
        check_url("http://10.0.0.1/x")
        assert False
    except ValueError:
        pass
    assert check_url("https://example.com/feed.xml").startswith("https://")


def test_parse_rss_and_match_watch_name():
    xml = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>中直股份中标</title>
        <link>https://example.com/a</link>
        <description>中直股份签署合同</description>
      </item>
    </channel></rss>"""
    items = parse_items(Document("https://example.com/rss", "application/rss+xml", xml.encode("utf-8")))
    assert items[0].title.startswith("中直")
    needles = watch_needles("中直股份", "600038", "国防军工", "")
    hits = match_item(items[0], [], [("600038", "中直股份", needles)])
    assert hits and hits[0].code6 == "600038"


def test_monitor_prefs_sources_unlock_news_and_scan(monkeypatch):
    rss = """<?xml version="1.0"?>
    <rss><channel>
      <item>
        <title>中直股份公告</title>
        <link>https://example.com/hit</link>
        <description>中直股份 600038 有新进展</description>
      </item>
    </channel></rss>"""

    def fake_fetch(url: str) -> Document:
        return Document(url, "application/rss+xml", rss.encode("utf-8"))

    monkeypatch.setattr("src.platform.web_sources.fetch_document", fake_fetch)
    monkeypatch.setattr("src.platform.web_sources.write_evidence", lambda *args, **kwargs: None)

    with TestClient(app) as client:
        headers = _auth(client)
        try:
            blocked = client.put(
                "/api/monitor/prefs",
                json={"sources": [{"name": "内网", "url": "http://127.0.0.1/x", "kind": "news"}]},
                headers=headers,
            )
            assert blocked.status_code == 400

            saved = client.put(
                "/api/monitor/prefs",
                json={
                    "sources": [
                        {
                            "name": "示例源",
                            "url": "https://example.com/rss.xml",
                            "kind": "news",
                            "keywords": [],
                        }
                    ]
                },
                headers=headers,
            )
            assert saved.status_code == 200, saved.text
            assert saved.json()["sources"][0]["url"] == "https://example.com/rss.xml"

            inst = client.put(
                "/api/monitor/prefs",
                json={"selected": saved.json()["selected"], "custom": saved.json()["custom"]},
                headers=headers,
            )
            assert inst.status_code == 200
            assert inst.json()["sources"]

            jobs = client.get("/api/monitor/jobs", headers=headers)
            by_key = {j["job_key"]: j for j in jobs.json()}
            assert by_key["news"]["enabled"] is True
            assert not by_key["news"]["reason"]
            assert by_key["policy"]["enabled"] is False

            db = SessionLocal()
            try:
                user = db.query(User).filter_by(username="hanish").first()
                db.query(Alert).filter_by(user_id=user.id, job_key="news").delete()
                db.commit()
            finally:
                db.close()

            ran = client.post("/api/monitor/jobs/news/run", json={}, headers=headers)
            assert ran.status_code == 200, ran.text
            body = ran.json()
            assert "news" in body["ran"]
            assert any(h["job_key"] == "news" and "中直" in h["title"] for h in body["hits"])
            assert "https://example.com/hit" in " ".join(h["detail"] for h in body["hits"])
        finally:
            client.put("/api/monitor/prefs", json={"sources": []}, headers=headers)
        jobs2 = client.get("/api/monitor/jobs", headers=headers)
        news = next(j for j in jobs2.json() if j["job_key"] == "news")
        assert news["enabled"] is False
        assert news["reason"]
