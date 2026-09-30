"""A 期：麦蕊请求的连接复用。

只验三件事：① 连接确实被复用（池只建一次）；② HTTP 次数一次都没变多；
③ 长连接被掐断时能自愈，开关关掉时能退回原来的 httpx.get。
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.config import settings
from src.market.client import MarketClient, reset_http_pool, shared_http_pool


@pytest.fixture(autouse=True)
def _clean_pool():
    reset_http_pool()
    yield
    reset_http_pool()


def _resp(status: int = 200, payload=None, text: str = "") -> httpx.Response:
    """手工构造的 Response 必须带上 request，否则 raise_for_status 会抛。"""
    req = httpx.Request("GET", "http://example.invalid/x")
    if payload is None:
        return httpx.Response(status, text=text, request=req)
    return httpx.Response(status, json=payload, request=req)


def _client() -> MarketClient:
    """不触发启动探针的裸实例（与 test_slow_cache.py 的构造方式一致）。"""
    client = MarketClient.__new__(MarketClient)
    client.offline = False
    client.sample_only = False
    client._timeout = 5.0
    client.licence = ""
    client.status = "unchecked"
    client._unusable = set()
    return client


def _fake_pool(monkeypatch):
    """把 httpx.Client 换成一个假的，返回 (fake, 构造次数列表)。"""
    created: list[int] = []
    fake = MagicMock()
    fake.get.return_value = _resp(200, [{"p": 1}])

    def _factory(*_args, **_kwargs):
        created.append(1)
        return fake

    monkeypatch.setattr(httpx, "Client", _factory)
    return fake, created


def test_pool_is_created_once(monkeypatch):
    monkeypatch.setattr(settings, "http_keepalive", True)
    _fake, created = _fake_pool(monkeypatch)

    shared_http_pool()
    shared_http_pool()
    shared_http_pool()

    assert len(created) == 1


def test_timeout_is_passed_per_request(monkeypatch):
    """启动探针会把 _timeout 临时调小：必须按次覆盖，不能吃池的默认值。"""
    monkeypatch.setattr(settings, "http_keepalive", True)
    fake, _ = _fake_pool(monkeypatch)
    client = _client()

    client._http_get("http://example.invalid/x")

    fake.get.assert_called_once_with("http://example.invalid/x", timeout=5.0)

    client._timeout = 1.5
    client._http_get("http://example.invalid/y")
    assert fake.get.call_args.kwargs["timeout"] == 1.5


def test_keepalive_off_uses_plain_get(monkeypatch):
    """开关关掉时必须与改动前逐字等价：httpx.get(url, timeout=...)。"""
    monkeypatch.setattr(settings, "http_keepalive", False)
    fake, created = _fake_pool(monkeypatch)
    client = _client()

    with patch.object(httpx, "get", return_value=_resp(200, {})) as plain:
        client._http_get("http://example.invalid/x")

    plain.assert_called_once_with("http://example.invalid/x", timeout=5.0)
    assert not created
    fake.get.assert_not_called()


def test_stale_connection_is_retried_once(monkeypatch):
    """服务端掐断空闲连接：重建一次就该成功，不能让整轮查询崩掉。"""
    monkeypatch.setattr(settings, "http_keepalive", True)
    fake, created = _fake_pool(monkeypatch)
    ok = _resp(200, [{"p": 1}])
    fake.get.side_effect = [httpx.RemoteProtocolError("server disconnected"), ok]
    client = _client()

    resp = client._http_get("http://example.invalid/x")

    assert resp is ok
    assert fake.get.call_count == 2
    assert len(created) == 2  # 旧池被关掉，重新建了一个


def test_client_closed_mid_flight_is_retried(monkeypatch):
    """并发窗口：别的线程刚把旧池关掉，手里这个 client 已经废了，同样要自愈。"""
    monkeypatch.setattr(settings, "http_keepalive", True)
    fake, _ = _fake_pool(monkeypatch)
    ok = _resp(200, [{"p": 1}])
    fake.get.side_effect = [
        RuntimeError("Cannot send a request, as the client has been closed."),
        ok,
    ]
    client = _client()

    assert client._http_get("http://example.invalid/x") is ok
    assert fake.get.call_count == 2


def test_stale_connection_fails_twice_then_raises(monkeypatch):
    """网络真的不通时不该无限重试：最多补一次。"""
    monkeypatch.setattr(settings, "http_keepalive", True)
    fake, _ = _fake_pool(monkeypatch)
    fake.get.side_effect = httpx.RemoteProtocolError("server disconnected")
    client = _client()

    with pytest.raises(httpx.RemoteProtocolError):
        client._http_get("http://example.invalid/x")

    assert fake.get.call_count == 2


def test_get_issues_exactly_one_http_call():
    """最关键的回归点：连接复用一次 HTTP 都不能多加。"""
    client = _client()
    reg = MagicMock()
    reg.iteration_plan.return_value = [("daily", "LIC-0001")]
    client._registry = reg

    with patch.object(client, "_http_get", return_value=_resp(200, [{"p": 10}])) as get:
        out = client._get("/hsrl/ssjy/000001")

    get.assert_called_once()
    assert out == [{"p": 10}]
    assert client.licence == "LIC-0001"


def test_get_retries_same_licence_on_429():
    """429 仍走同一张证重试一次（原有的限频语义，不因换池而改变）。"""
    client = _client()
    reg = MagicMock()
    reg.iteration_plan.return_value = [("daily", "LIC-0001")]
    client._registry = reg

    ok = _resp(200, [{"p": 10}])
    with patch.object(client, "_http_get", side_effect=[_resp(429, text="too many"), ok]) as get:
        with patch("src.market.client.time.sleep") as sleep:
            out = client._get("/hsrl/ssjy/000001")

    assert get.call_count == 2
    assert out == [{"p": 10}]
    sleep.assert_called_once_with(0.8)
    # 429 是限频不是额度用尽：不能把这张证标记为用尽
    reg.mark_quota_exhausted.assert_not_called()
