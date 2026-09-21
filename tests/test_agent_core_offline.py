from fastapi.testclient import TestClient

from src.agents.llm import DEEPSEEK_BASE, DEEPSEEK_CHAT
from src.config import Settings
from src.main import app
from src.market.client import MarketClient, resolve_instruments
from src.tools.table_parse import extract_codes, looks_like_table, parse_table_text


def _auth(client: TestClient) -> dict:
    login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.json()['token']}"}


PASTED = "代码\t名称\n600038.SH\t中直股份\n000725.SZ\t京东方A\n"


def test_deepseek_is_default_llm():
    assert Settings.model_fields["llm_provider"].default == "deepseek"
    assert Settings.model_fields["llm_base_url"].default == DEEPSEEK_BASE
    assert Settings.model_fields["llm_model"].default == DEEPSEEK_CHAT


def test_parse_pasted_tsv_extracts_codes():
    assert looks_like_table(PASTED)
    sheet = parse_table_text(PASTED)
    assert sheet["codes"] == ["600038.SH", "000725.SZ"]
    assert sheet["rows"][0]["名称"] == "中直股份"
    assert extract_codes("问 600519 和 002230.SZ") == ["600519", "002230.SZ"]


def test_history_respects_limit():
    market = MarketClient()
    inst = resolve_instruments(["600038.SH"], market)[0]
    bars = market.history(inst, limit=5)
    assert len(bars) == 5
    assert bars[-1]["d"] >= bars[0]["d"]


def test_health_lists_core_tools_and_deepseek():
    with TestClient(app) as client:
        health = client.get("/api/health")
        body = health.json()
        tools = set(body["agent"]["tools"])
        assert {"excel_parse", "warehouse_get", "market_fetch"} <= tools
        assert "provider" in body["agent"]["llm_status"]
        assert "excel_parse" in body["agent"]["analyst_tools"]


def test_chat_parses_pasted_excel_and_quotes():
    with TestClient(app) as client:
        headers = _auth(client)
        chat = client.post(
            "/api/agent/chat",
            json={
                "question": "帮我看看这张粘贴表的现价",
                "attachments": [{"kind": "text", "name": "pasted.tsv", "text": PASTED}],
            },
            headers=headers,
        )
        assert chat.status_code == 200, chat.text
        body = chat.json()
        ids = {t["id"] for t in body["tools"]}
        assert "excel_parse" in ids
        assert "quote" in ids
        assert "market_fetch" not in ids
        assert "26.86" in body["answer"] or "中直" in body["answer"]


def test_warehouse_and_market_fetch_tools():
    with TestClient(app) as client:
        headers = _auth(client)
        hist = client.post(
            "/api/agent/chat",
            json={"question": "中直股份日线历史数据最近几天"},
            headers=headers,
        )
        assert hist.status_code == 200, hist.text
        assert "warehouse_get" in {t["id"] for t in hist.json()["tools"]}
        assert "日线" in hist.json()["answer"] or "24.6" in hist.json()["answer"] or "中直" in hist.json()["answer"]

        live = client.post(
            "/api/agent/chat",
            json={"question": "用接口查一下中直股份现价"},
            headers=headers,
        )
        assert live.status_code == 200, live.text
        live_ids = {t["id"] for t in live.json()["tools"]}
        assert "quote" in live_ids
        assert "market_fetch" not in live_ids
        assert "26.86" in live.json()["answer"]
