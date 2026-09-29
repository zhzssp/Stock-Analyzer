"""S3（正确）回归：工具开关真的生效、输出守门、会话与流式可靠性。

对应缺陷：
- D2/D3：yaml 清单恒挂空壳 + /agent/tools/reload 对工具是空操作
- D10：always_tools / forbidden 声明了但运行时不执行
- D8/D9：流式中断整轮丢失、无 error 事件
- D13：load_policy 对未知 agent 静默降级为 analyst
- D12：会话标题取原文 128 字
"""

import tempfile
from pathlib import Path

import pytest
import yaml

from src.tools.base import ToolResult, ToolSpec
from src.tools.registry import registry


def test_manifest_updates_switch_without_replacing_impl():
    """改 yaml 的 enabled 要能生效（热重载），且不能把代码里的真实现换成空壳。"""
    from src.tools.loader import load_manifests

    def real_fn(args, ctx):
        return ToolResult(ok=True, data="real", source="s3_probe")

    registry.register(
        ToolSpec(id="s3_probe", name="探测", kind="test", description="", input_schema={"type": "object", "properties": {}}, enabled=True),
        real_fn,
    )
    folder = Path(tempfile.mkdtemp())
    (folder / "s3_probe.yaml").write_text(
        yaml.safe_dump({"id": "s3_probe", "enabled": False, "reason": "临时关闭"}, allow_unicode=True),
        encoding="utf-8",
    )

    load_manifests(folder)

    assert registry.get("s3_probe").enabled is False, "yaml 应能更新开关（以前这里是 continue，改了完全没用）"
    assert registry.fn_of("s3_probe") is real_fn, "不能把真实现替换成空壳"


def test_manifest_only_tool_is_placeholder_not_silent_success():
    """清单里有、代码里没实现 → 必须是明确失败的空壳，而不是假装能用。"""
    from src.tools.loader import load_manifests

    folder = Path(tempfile.mkdtemp())
    (folder / "s3_missing.yaml").write_text(
        yaml.safe_dump({"id": "s3_missing", "name": "没有实现的工具", "enabled": False, "reason": "还没做"}, allow_unicode=True),
        encoding="utf-8",
    )
    load_manifests(folder)

    fn = registry.fn_of("s3_missing")
    assert fn is not None
    assert getattr(fn, "is_disabled_placeholder", False) is True
    out = fn({}, None)
    assert out.ok is False


def test_guard_answer_flags_advice_wording():
    from src.agents.policy import guard_answer

    clean = guard_answer("平安银行现价 11.2 元，涨 1.2%")
    assert clean == "平安银行现价 11.2 元，涨 1.2%", "正常回答不该被改"

    guarded = guard_answer("该股建议买入", forbidden=("荐股",))
    assert "建议买入" in guarded
    assert "不提供买卖建议" in guarded


def test_load_policy_rejects_unknown_agent():
    from src.agents.policy import load_policy

    assert load_policy("analyst").id == "analyst"
    assert load_policy("researcher").id == "researcher"
    with pytest.raises(ValueError):
        load_policy("reviewer"), "未知 agent 以前会静默读 analyst 的配置"


def test_session_title_is_trimmed():
    from src.agents.sessions import create_session
    from src.db import SessionLocal
    from src.models import User

    db = SessionLocal()
    try:
        user = db.query(User).filter_by(username="hanish").first()
        long_q = "请问" + "平" * 200
        row = create_session(db, user, "analyst", long_q)
        assert len(row.title) <= 40, f"标题不该是整条问题，实际 {len(row.title)} 字"
        db.delete(row)
        db.commit()
    finally:
        db.close()


def test_chat_stream_emits_error_event_instead_of_dropping(monkeypatch):
    """流里抛异常要变成 error 事件，前端才看得到原因（以前是直接断流）。"""
    from fastapi.testclient import TestClient

    from src.api import routes
    from src.main import app

    def boom(*args, **kwargs):
        raise RuntimeError("流炸了")

    monkeypatch.setattr(routes, "iter_agent", boom)

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        res = client.post("/api/agent/chat", json={"question": "测试一下", "stream": True}, headers=headers)
        assert res.status_code == 200
        assert '"type": "error"' in res.text or '"type":"error"' in res.text, res.text[:300]
        assert "流炸了" in res.text


def test_chat_rejects_unknown_session_id():
    """传了不存在的 session_id 要报错，不能静默新建（否则 session_id 悄悄变化、历史链断裂）。"""
    from fastapi.testclient import TestClient

    from src.main import app

    with TestClient(app) as client:
        login = client.post("/api/auth/login", json={"username": "hanish", "password": "change-me"})
        headers = {"Authorization": f"Bearer {login.json()['token']}"}
        res = client.post("/api/agent/chat", json={"question": "测试", "session_id": 99999999}, headers=headers)
        assert res.status_code == 404
