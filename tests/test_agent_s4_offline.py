"""S4：Agent 与监控共用同一份白名单检索源。

以前：监控侧用 scan_sources + sources_for，Agent 侧的 web_finance_search / policy_news
是空壳（_disabled_run）。现在两个工具都接到同一条链路上：
- 没配源 → 明确报错，不编内容
- 配了源 → 返回命中的标题 / URL / 摘要（与监控同一份源、同一种匹配）
"""

from types import SimpleNamespace

from src.tools.base import ToolContext


def _hit():
    return SimpleNamespace(
        code6="600038",
        name="中直股份",
        source_name="示例源",
        title="中直股份获大额订单",
        url="https://example.com/hit",
        snippet="……中直股份……",
        needles=["中直股份"],
    )


def test_source_tool_reports_missing_sources(monkeypatch):
    """没配检索源时要说清楚，不能静默返回空、更不能编内容。"""
    from src.tools import research_tools

    monkeypatch.setattr("src.platform.monitor_prefs.sources_for", lambda db, uid: [])
    ctx = ToolContext(user_id=1, db=None, market=None, engine=None)

    out = research_tools.web_finance_search({"query": "中直股份"}, ctx)
    assert out.ok is False
    assert "检索源" in (out.error or "")

    out2 = research_tools.policy_news({"industry": "有色金属"}, ctx)
    assert out2.ok is False
    assert "检索源" in (out2.error or "")


def test_source_tool_returns_hits_from_whitelist(monkeypatch):
    """配了源就走同一条链路：命中的是白名单里的条目，带 URL 可核对。"""
    from src.tools import research_tools

    monkeypatch.setattr(
        "src.platform.monitor_prefs.sources_for",
        lambda db, uid: [{"enabled": True, "kind": "news", "name": "示例源", "url": "https://example.com/rss.xml"}],
    )
    monkeypatch.setattr("src.platform.web_sources.scan_sources", lambda *a, **k: [_hit()])

    ctx = ToolContext(user_id=1, db=None, market=None, engine=None)

    out = research_tools.web_finance_search({"query": "中直股份"}, ctx)
    assert out.ok is True
    rows = out.data
    assert rows and rows[0]["title"] == "中直股份获大额订单"
    assert rows[0]["url"] == "https://example.com/hit"

    out2 = research_tools.policy_news({"query": "低空经济"}, ctx)
    assert out2.ok is True


def test_source_tools_are_enabled_with_real_impl():
    """U2/U3 的旧契约是「保持关闭」；接上实现后应为启用且非空壳。"""
    from src.tools import registry

    for tool_id in ("web_finance_search", "policy_news"):
        assert registry.get(tool_id).enabled is True
        fn = registry.fn_of(tool_id)
        assert fn is not None
        assert not getattr(fn, "is_disabled_placeholder", False)
