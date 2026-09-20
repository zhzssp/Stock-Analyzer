from src.agents.policy import load_policy, reload_policies, research_hints
from src.agents.runner import pick_agent


def test_policies_load_from_yaml():
    reload_policies()
    analyst = load_policy("analyst")
    researcher = load_policy("researcher")
    assert "watch_card" in analyst.tools
    assert "watch_review" in analyst.tools
    assert "watch_rules" in analyst.tools
    assert "watch_rules" in researcher.tools
    assert "watch_review" in researcher.tools
    assert "query_run" in analyst.tools
    assert "excel_parse" in analyst.tools
    assert "excel_parse" not in researcher.tools
    assert "query_run" not in researcher.tools
    assert researcher.inject_today_queue is True
    assert analyst.inject_watch_hits is False
    assert "看市场" in research_hints()
    assert any("荐股" in r for r in analyst.rules)


def test_pick_agent_uses_research_hints():
    assert pick_agent("中直股份现价", "auto") == "analyst"
    assert pick_agent("看市场：自选相关", "auto") == "researcher"
