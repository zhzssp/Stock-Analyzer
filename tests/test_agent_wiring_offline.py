"""三处接线：关键词能问到公告/资讯/政策/龙虎榜，回答守门，期货只报品种名。"""

from src.agents.planner import _draft_lines, heuristic_plan
from src.agents.policy import load_policy, reload_policies
from src.agents.runner import iter_agent
from src.tools.base import ToolContext
from src.market.client import MarketClient


def _ctx(agent: str = "analyst") -> ToolContext:
    reload_policies()
    ctx = ToolContext(user_id=0, db=None, market=MarketClient(), engine=None)
    ctx.allowed_tools = load_policy(agent).tools
    ctx.agent_name = agent
    return ctx


def _ids(question: str, agent: str = "analyst") -> list[str]:
    return [c["id"] for c in heuristic_plan(question, set(), _ctx(agent))]


def test_chat_keywords_select_disclosure_news_policy_breadth():
    assert "corp_disclosure" in _ids("中直股份有没有新公告")
    news = heuristic_plan("中直股份有什么新闻", set(), _ctx())
    web = next(c for c in news if c["id"] == "web_finance_search")
    assert web["args"].get("name") == "中直股份"
    assert "policy_news" not in [c["id"] for c in news]
    assert "policy_news" in _ids("低空经济有什么政策")
    assert "market_breadth" in _ids("今天龙虎榜怎么样")


def test_market_view_does_not_auto_call_those_tools():
    ids = _ids("看市场：当前和自选相关的市场在发生什么？", "researcher")
    assert "universe" in ids
    assert "futures_quote" not in ids
    for tool_id in ("web_finance_search", "policy_news", "market_breadth", "corp_disclosure"):
        assert tool_id not in ids


def test_draft_keeps_news_titles_and_futures_names():
    news = _draft_lines(
        [
            {
                "id": "web_finance_search",
                "ok": True,
                "cite": "检索源 · 资讯",
                "data": [{"title": "中直再签合同", "url": "https://example.com/a"}],
            }
        ]
    )
    assert "中直再签合同" in news[0]
    assert "https://example.com/a" in news[0]

    futures = _draft_lines(
        [
            {
                "id": "futures_map",
                "ok": True,
                "cite": "期货映射",
                "data": [{"name": "中直股份", "contracts": [{"name": "沪铜"}]}],
            }
        ]
    )
    assert "沪铜" in futures[0]
    assert "无期货价格" in futures[0]


def test_runner_appends_guard_note(monkeypatch):
    import src.agents.runner as runner

    monkeypatch.setattr(runner, "plan", lambda *args, **kwargs: [])
    monkeypatch.setattr(runner, "write_answer", lambda *args, **kwargs: ("该股建议买入", []))
    events = list(iter_agent("随便问", _ctx()))
    done = events[-1]
    assert done["type"] == "done"
    assert "建议买入" in done["answer"]
    assert "不提供买卖建议" in done["answer"]
    assert "荐股" not in done["answer"]
