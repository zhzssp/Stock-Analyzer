from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from sqlalchemy.orm import Session

from src.market.client import MarketClient
from src.query.engine import QueryEngine


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
