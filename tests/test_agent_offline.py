from fastapi.testclient import TestClient

from src.main import app


def _auth(client: TestClient) -> dict:
    login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


def test_analyst_quote_holders_and_finance():
    with TestClient(app) as client:
        headers = _auth(client)
        health = client.get("/api/health")
        assert health.json()["agent"]["id"] == "analyst"
        assert "quote" in health.json()["agent"]["tools"]

        chat = client.post(
            "/api/agent/chat",
            json={"question": "中直股份现价和十大股东？研发费用呢？"},
            headers=headers,
        )
        assert chat.status_code == 200, chat.text
        body = chat.json()
        assert "26.86" in body["answer"]
        assert "控股股东" in body["answer"] or "股东" in body["answer"]
        assert "19.4" in body["answer"]
        ids = {t["id"] for t in body["tools"]}
        assert {"quote", "holders_flow", "finance_snapshot"} <= ids
        assert any("quote" in (c.get("cite") or "") or c.get("source") == "quote" for c in body["cites"])


def test_analyst_reports_bottom_from_bars():
    with TestClient(app) as client:
        headers = _auth(client)
        chat = client.post(
            "/api/agent/chat",
            json={"question": "中直股份离底部还有多远？目标卖价是多少？"},
            headers=headers,
        )
        body = chat.json()
        assert chat.status_code == 200
        assert "24.6" in body["answer"]
        assert "36.9" in body["answer"]
        assert "bottom" in {t["id"] for t in body["tools"]}


def test_analyst_cites_exported_excel():
    with TestClient(app) as client:
        headers = _auth(client)
        exported = client.post("/api/query/export", json={"pool_name": "自选"}, headers=headers)
        assert exported.status_code == 200
        filename = exported.json()["filename"]

        chat = client.post(
            "/api/agent/chat",
            json={"question": "最近导出的 Excel 档案里有什么？"},
            headers=headers,
        )
        body = chat.json()
        assert chat.status_code == 200, chat.text
        blob = body["answer"] + str(body["cites"])
        assert filename in blob
        assert {t["id"] for t in body["tools"]} & {"excel_list", "excel_read"}

        exported_turn = client.post(
            "/api/agent/export",
            json={"question": "最近导出的 Excel 档案里有什么？", "answer": body["answer"], "cites": body["cites"], "tools": body["tools"]},
            headers=headers,
        )
        assert exported_turn.status_code == 200
        assert exported_turn.json()["filename"].endswith("_agent.xlsx")


def test_bj_finance_returns_fixture():
    with TestClient(app) as client:
        headers = _auth(client)
        chat = client.post(
            "/api/agent/chat",
            json={"question": "星昊医药的研发费用是多少？"},
            headers=headers,
        )
        body = chat.json()
        assert chat.status_code == 200
        assert "0.8" in body["answer"]
