import json

from fastapi.testclient import TestClient

from src.main import app
from src.market.client import MarketClient, MarketError
from src.market.client import resolve_instruments
from src.query.engine import QueryEngine
from src.query.issues import friendly_failure, summarize_issues


def test_http_404_reads_as_query_failure_without_licence():
    import httpx

    secret = "1F33187D-93A9-4164-9BC4-C5F25B6AC0AB"
    url = f"https://api.mairuiapi.com/hsstock/financial/flowholder/688006.SH/{secret}"
    request = httpx.Request("GET", url)
    response = httpx.Response(404, request=request)
    exc = httpx.HTTPStatusError("boom", request=request, response=response)
    text = friendly_failure(exc)
    assert text == "查询失败（HTTP 404 Not Found）"
    assert secret not in text
    raw = (
        "Client error '404 Not Found' for url "
        f"'{url}' For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404"
    )
    assert friendly_failure(raw) == text
    assert friendly_failure("请求过于频繁，这一项暂未取到，稍后再试即可。").startswith("请求过于频繁")

    market = MarketClient()
    market.open_query_issues()
    market.note_issue("holders", raw, "688006")
    market.note_issue("holders", raw.replace("688006", "688025"), "688025")
    rows = summarize_issues(market.close_query_issues())
    assert rows[0]["message"] == "查询失败（HTTP 404 Not Found）"
    assert rows[0]["count"] == 2
    assert secret not in rows[0]["message"]


def test_same_failure_collapses_to_one_line():
    market = MarketClient()
    market.open_query_issues()
    market.note_issue("finance", "Licence 额度已用尽", "600038")
    market.note_issue("finance", "Licence 额度已用尽", "000725")
    market.note_issue("finance", "Licence 额度已用尽", "600038")
    closed = market.close_query_issues()
    market.note_issue("finance", "不应该记下", "600038")
    assert market.close_query_issues() == []
    rows = summarize_issues(closed)
    assert rows == [
        {
            "level": "error",
            "block": "finance",
            "message": "Licence 额度已用尽",
            "count": 2,
            "codes": ["600038", "000725"],
        }
    ]


def test_missing_quotes_are_reported_before_slow_fields():
    market = MarketClient()

    def boom(_insts, cancel=None):
        raise MarketError("Licence 额度已用尽")

    market.quotes_many = boom
    seen: list[dict] = []
    engine = QueryEngine(market)
    insts = resolve_instruments(["600038.SH"], market)
    rows = engine.run(
        insts,
        ["name", "price"],
        refresh_mode="full",
        force_live=True,
        on_issue=seen.append,
    )
    assert rows[0]["name"] == "中直股份"
    assert rows[0]["price"] is None
    assert seen and seen[0][0]["block"] == "quote"
    assert seen[0][0]["level"] == "error"
    assert engine.last_issues[0]["block"] == "quote"
    assert "额度" in engine.last_issues[0]["message"]


def _events(text: str) -> list[tuple[str, dict]]:
    out = []
    for chunk in text.split("\n\n"):
        event = ""
        data = None
        for line in chunk.splitlines():
            if line.startswith("event:"):
                event = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data = json.loads(line.split(":", 1)[1].strip())
        if event:
            out.append((event, data or {}))
    return out


def test_small_pool_stream_emits_quote_batch_before_done():
    """不满 10 只时，行情批必须仍以 quote 发出。标成 full 会让页面画不出任何行。"""
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        res = client.post(
            "/api/query/stream",
            json={"codes": ["600038.SH", "000725.SZ"], "refresh_mode": "quote", "fields": ["name", "code", "price"]},
            headers=headers,
        )
        assert res.status_code == 200, res.text
        events = _events(res.text)
        batches = [data for name, data in events if name == "batch"]
        assert batches
        assert batches[0]["stage"] == "quote"
        assert {row["code6"] for row in batches[0]["rows"]} == {"600038", "000725"}
        done = next(data for name, data in events if name == "done")
        assert done["rows_count"] == 2
        assert done["has_more"] is False


def test_stream_sends_field_objects_and_issues():
    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        res = client.post(
            "/api/query/stream",
            json={"refresh_mode": "quote", "pool": "watch"},
            headers=headers,
        )
        assert res.status_code == 200, res.text
        events = _events(res.text)
        meta = next(data for name, data in events if name == "meta")
        assert isinstance(meta["fields"][0], dict)
        assert meta["fields"][0]["key"]
        assert meta["fields"][0]["label"]
        done = next(data for name, data in events if name == "done")
        assert "issues" in done
        body = client.post("/api/query/run", json={"refresh_mode": "quote", "pool": "watch"}, headers=headers)
        assert body.status_code == 200
        assert body.json()["issues"] == []
        assert body.json()["rows"][0]["name"]


def test_history_error_is_reported_on_the_bars_block():
    market = MarketClient()

    def boom(inst, *args, **kwargs):
        market.note_issue("bars", "Licence 额度已用尽", inst.code6)
        return []

    market.history = boom
    engine = QueryEngine(market)
    rows = engine.run(
        resolve_instruments(["600038.SH"], market),
        ["name", "low1y"],
        refresh_mode="full",
    )
    assert rows[0]["low1y"] is None
    hits = [item for item in engine.last_issues if item["block"] == "bars" and "额度" in item["message"]]
    assert len(hits) == 1
