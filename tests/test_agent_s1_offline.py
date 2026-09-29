"""S1（止血）回归：工具走缓存、涨跌停池缓存、调度出错留痕 + 日终补跑标记。

这三条都对应「已经做了但做得不对」的缺陷：
- 问答 / Agent 工具以前跑在 full 模式，缓存写了却读不到（白烧额度）
- 涨跌停池盘中每 5 分钟各打一次接口
- 调度一处异常 → 整轮（含复盘、配额清理）静默不跑；20:20 错过即永久丢失
"""

from types import SimpleNamespace

import pytest

from src.config import settings


def test_tool_run_defaults_to_cache_mode_and_restores():
    """工具调用期间慢字段走缓存，结束后必须还原 —— 不能影响后续查询。"""
    from src.tools.base import ToolContext, ToolResult, ToolSpec
    from src.tools.registry import registry

    seen = {}

    def probe(args, ctx):
        seen["during"] = getattr(ctx.market, "query_refresh_mode", None)
        return ToolResult(ok=True, data="ok", source="probe")

    spec = ToolSpec(
        id="s1_cache_probe",
        name="缓存探针",
        kind="test",
        description="",
        input_schema={"type": "object", "properties": {}},
        enabled=True,
    )
    registry.register(spec, probe)
    market = SimpleNamespace(query_refresh_mode="full")
    ctx = ToolContext(user_id=1, db=None, market=market, engine=None)

    out = registry.run("s1_cache_probe", {}, ctx)

    assert out.ok is True
    assert seen.get("during") == "cache", "工具执行时应处于 cache 模式（慢字段走本机缓存）"
    assert market.query_refresh_mode == "full", "工具执行完必须还原，不能污染后续"


def test_tool_run_restores_mode_even_when_tool_raises():
    from src.tools.base import ToolContext, ToolSpec
    from src.tools.registry import registry

    def boom(args, ctx):
        raise RuntimeError("工具炸了")

    spec = ToolSpec(
        id="s1_cache_probe_raise",
        name="会炸的探针",
        kind="test",
        description="",
        input_schema={"type": "object", "properties": {}},
        enabled=True,
    )
    registry.register(spec, boom)
    market = SimpleNamespace(query_refresh_mode="full")
    ctx = ToolContext(user_id=1, db=None, market=market, engine=None)

    out = registry.run("s1_cache_probe_raise", {}, ctx)

    assert out.ok is False
    assert market.query_refresh_mode == "full"


def test_limit_pool_codes_hits_cache(monkeypatch, tmp_path):
    """同一天的池子第二次不再打接口（盘中 5 分钟一轮，池子不会几分钟变一次）。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "limit_pool_ttl_sec", 300)

    from src.market.client import MarketClient

    client = MarketClient.__new__(MarketClient)
    client.offline = False
    client.sample_only = False
    calls = {"n": 0}

    def fake_try_get(path):
        calls["n"] += 1
        return [{"dm": "600000"}, {"dm": "000001"}]

    client._try_get = fake_try_get

    first = client.limit_pool_codes("up")
    second = client.limit_pool_codes("up")

    assert first == {"600000", "000001"}
    assert second == first
    assert calls["n"] == 1, "第二次应命中缓存，不再打接口"


def test_limit_pool_empty_result_is_not_cached(monkeypatch, tmp_path):
    """取空不缓存：否则一次网络抖动会把「今天没有涨停」这个假结论缓存住。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "limit_pool_ttl_sec", 300)

    from src.market.client import MarketClient

    client = MarketClient.__new__(MarketClient)
    client.offline = False
    client.sample_only = False
    calls = {"n": 0}

    def fake_try_get(path):
        calls["n"] += 1
        return []

    client._try_get = fake_try_get

    assert client.limit_pool_codes("up") == set()
    assert client.limit_pool_codes("up") == set()
    assert calls["n"] == 2, "空结果不能进缓存，否则会一直返回空"


def test_eod_marker_roundtrip(monkeypatch, tmp_path):
    """20:20 补跑靠这个标记判断今天有没有跑过。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    from src.platform.scheduler import last_eod_day, mark_eod_done

    assert last_eod_day() == "", "没跑过时不应有标记"
    mark_eod_done("2026-09-29")
    assert last_eod_day() == "2026-09-29"
    mark_eod_done("2026-09-30")
    assert last_eod_day() == "2026-09-30"


def test_log_scheduler_error_never_raises(monkeypatch, tmp_path):
    """记日志这件事本身不能再抛异常，否则会把调度一起拖死。"""
    monkeypatch.setattr(settings, "data_dir", tmp_path)

    from src.platform.scheduler import log_scheduler_error

    log_scheduler_error("测试", RuntimeError("boom"))
    log_file = tmp_path / "logs" / "scheduler.log"
    assert log_file.exists()
    assert "boom" in log_file.read_text(encoding="utf-8")
