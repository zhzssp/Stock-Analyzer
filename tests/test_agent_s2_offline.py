"""S2（可用）回归：规划器不再「有 Key 却拿不到工具结果」，静默失败改可见。

对应缺陷：
- P0-4：LLM 返回空 tool_calls 时不回退启发式；模型原文被丢弃；参数解析失败盲调
- A8：自定义规则校验失败被静默 continue（界面显示「已启用」实际永不跑）
- A5：提醒档位 as_of 只进总线不进库
"""

from types import SimpleNamespace

from src.db import SessionLocal
from src.models import Alert, User, UserRule
from src.tools.base import ToolContext


def _ctx(**kw) -> ToolContext:
    base = dict(user_id=1, db=None, market=None, engine=None)
    base.update(kw)
    return ToolContext(**base)


def test_plan_falls_back_to_heuristic_on_empty_tool_calls():
    """空列表不能被当成有效结果：以前 `if llm_calls is not None` 会直接返回 []。"""
    from src.agents import planner

    seen = {}

    def fake_llm_plan(*args, **kwargs):
        return [], "模型原话"

    def fake_heuristic(*args, **kwargs):
        seen["called"] = True
        return [{"id": "quote", "args": {}}]

    original_llm = planner.llm_plan
    original_heu = planner.heuristic_plan
    planner.llm_plan = fake_llm_plan
    planner.heuristic_plan = fake_heuristic
    try:
        ctx = _ctx()
        calls = planner.plan("平安银行怎么样", [], ctx)
    finally:
        planner.llm_plan = original_llm
        planner.heuristic_plan = original_heu

    assert seen.get("called") is True, "空 tool_calls 必须回退启发式"
    assert calls and calls[0]["id"] == "quote"
    assert ctx.llm_direct_answer == "模型原话", "模型自己写的回答不能丢"


def test_write_answer_uses_direct_answer_instead_of_no_tool_message():
    """没调到工具时，如果模型已经回答了就该用它的，而不是报「没有可用 Tool」。"""
    from src.agents import planner

    ctx = _ctx()
    ctx.llm_direct_answer = "模型说：现价 11.2 元"
    text, _ = planner.write_answer("平安银行现价多少", [], ctx=ctx)
    assert "11.2" in text
    assert "没有调用到可用 Tool" not in text


def test_write_answer_keeps_fallback_when_no_direct_answer():
    from src.agents import planner

    text, _ = planner.write_answer("随便问问", [], ctx=_ctx())
    assert "没有调用到可用 Tool" in text


def test_bad_tool_arguments_are_skipped_not_called_with_raw_question():
    """参数不是合法 JSON 时跳过并留痕，不能拿原话盲调一次工具。"""
    from src.agents import planner

    forced = {"tool_choice": None}

    def fake_chat(messages, tools, tool_choice="auto"):
        forced["tool_choice"] = tool_choice
        return SimpleNamespace(
            error=None,
            message={
                "content": "",
                "tool_calls": [{"function": {"name": "quote", "arguments": "{不是 JSON"}}],
            },
        )

    original = planner.chat_completions
    planner.chat_completions = fake_chat
    try:
        planner.llm_available = lambda: True
        planner.llm_supports_tools = lambda: True
        ctx = _ctx()
        ctx.allowed_tools = ["quote"]
        calls, direct = planner.llm_plan("平安银行", [], set(), ctx)
    finally:
        planner.chat_completions = original

    assert calls == [], "非法参数应被跳过，不能盲调"
    assert ctx.llm_notice and "不是合法 JSON" in ctx.llm_notice


def test_invalid_custom_rule_is_reported_not_silently_skipped():
    """校验不过的规则要出现在 invalid_rules 里，而不是静默消失。"""
    from src.api.routes import market
    from src.agents.watcher import run_watcher

    db = SessionLocal()
    rule = None
    try:
        user = db.query(User).filter_by(username="hanish").first()
        rule = UserRule(
            user_id=user.id,
            name="永远跑不了的坏规则",
            spec='{"metric": "not_a_real_metric", "op": "gte", "value": 1}',
            enabled=1,
        )
        db.add(rule)
        db.commit()
        out = run_watcher(db, user, market, schedule="eod")
        names = [r.get("name") for r in out.get("invalid_rules", [])]
        assert "永远跑不了的坏规则" in names, f"坏规则应被报出来，实际：{out.get('invalid_rules')}"
    finally:
        if rule is not None:
            db.delete(rule)
            db.commit()
        db.close()


def test_alert_payload_exposes_as_of():
    """档位要能通过 API 拿到，不然复盘没法按档位筛。"""
    from fastapi.testclient import TestClient

    from src.main import app

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        alerts = client.get("/api/alerts", headers=headers).json()
        for item in alerts:
            assert "as_of" in item

        db = SessionLocal()
        try:
            user = db.query(User).filter_by(username="hanish").first()
            assert hasattr(Alert(user_id=user.id), "as_of")
        finally:
            db.close()
