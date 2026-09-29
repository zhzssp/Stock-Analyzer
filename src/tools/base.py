from __future__ import annotations

import contextlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from src.config import settings
from src.market.client import MarketClient
from src.query.engine import QueryEngine


@contextlib.contextmanager
def market_cache_mode(ctx: ToolContext | None, mode: str = "cache"):
    """工具调用期间让「慢字段」走本机缓存：档案 / 股东 / 财务 / 资金流。

    现价不走这条缓存（_slow_load 只服务慢字段，行情另有链路），
    所以这里改成 cache 不会让「现在多少钱」变旧，只会避免重复打麦蕊。
    """
    market = getattr(ctx, "market", None) if ctx is not None else None
    if market is None or not getattr(settings, "agent_tool_cache_default", True):
        yield
        return
    previous = getattr(market, "query_refresh_mode", "full")
    market.query_refresh_mode = mode
    try:
        yield
    finally:
        market.query_refresh_mode = previous


@dataclass
class ToolContext:
    user_id: int
    db: Session
    market: MarketClient
    engine: QueryEngine
    attachments: list[dict] = field(default_factory=list)
    allowed_tools: list[str] | None = None
    history: list[dict] = field(default_factory=list)
    agent_name: str = "analyst"
    llm_notice: str | None = None


@dataclass
class ToolResult:
    ok: bool
    data: Any = None
    source: str = ""
    as_of: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    error: str | None = None
    cite: str = ""

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "data": self.data,
            "source": self.source,
            "as_of": self.as_of,
            "error": self.error,
            "cite": self.cite,
        }


@dataclass(frozen=True)
class ToolSpec:
    id: str
    name: str
    kind: str
    description: str
    input_schema: dict
    enabled: bool = True
    reason: str = ""


ToolFn = Callable[[dict, ToolContext], ToolResult]
