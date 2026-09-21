import httpx

from src.agents.llm import LLM_ERR_BALANCE, LLM_ERR_REQUEST, llm_failure_message
from src.agents.planner import _prepend_llm_notice, heuristic_plan, write_answer
from src.agents.policy import load_policy
from src.tools.base import ToolContext
from src.market.client import MarketClient


def test_llm_failure_message_balance():
    req = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    resp = httpx.Response(402, request=req, text='{"error":{"message":"Insufficient Balance"}}')
    exc = httpx.HTTPStatusError("402", request=req, response=resp)
    assert llm_failure_message(exc) == LLM_ERR_BALANCE


def test_llm_failure_message_generic():
    req = httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions")
    resp = httpx.Response(500, request=req, text="internal error")
    exc = httpx.HTTPStatusError("500", request=req, response=resp)
    assert llm_failure_message(exc) == LLM_ERR_REQUEST


def _analyst_ctx() -> ToolContext:
    ctx = ToolContext(user_id=0, db=None, market=MarketClient(), engine=None)
    ctx.allowed_tools = load_policy("analyst").tools
    return ctx


def test_heuristic_dedupes_market_fetch_and_quote():
    calls = heuristic_plan("给出科大讯飞的实时股票行情", set(), _analyst_ctx())
    ids = [c["id"] for c in calls]
    assert ids == ["quote"]


def test_heuristic_keeps_market_fetch_when_only_api_hint():
    calls = heuristic_plan("用接口查600038", set(), _analyst_ctx())
    ids = [c["id"] for c in calls]
    assert ids == ["market_fetch"]
    assert calls[0]["args"]["resource"] == "quote"


def test_heuristic_dedupes_flow_tools():
    calls = heuristic_plan("600038资金净流入接口", set(), _analyst_ctx())
    ids = [c["id"] for c in calls]
    assert "capital_flow" in ids
    assert "market_fetch" not in ids


def test_write_answer_prepends_balance_notice():
    ctx = ToolContext(user_id=0, db=None, market=MarketClient(), engine=None)
    ctx.llm_notice = LLM_ERR_BALANCE
    obs = [
        {
            "id": "quote",
            "ok": True,
            "cite": "行情",
            "source": "quote",
            "data": [{"name": "科大讯飞", "code": "002230.SZ", "price": 41.25, "pct": -1.06, "pe": 48.6}],
        }
    ]
    answer, _ = write_answer("科大讯飞行情", obs, ctx=ctx)
    assert answer.startswith(f"⚠️ {LLM_ERR_BALANCE}")
    assert "41.25" in answer
