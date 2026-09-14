from __future__ import annotations

import uuid
from collections import defaultdict, deque
from datetime import datetime
from typing import Any, Callable

Handler = Callable[[dict], None]


class AgentBus:
    def __init__(self, retain: int = 200) -> None:
        self._subs: dict[str, list[Handler]] = defaultdict(list)
        self._log: deque[dict] = deque(maxlen=retain)
        self._seen: deque[str] = deque(maxlen=retain)

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    def publish(
        self,
        topic: str,
        payload: Any,
        source_agent: str,
        idempotency_key: str | None = None,
    ) -> dict | None:
        key = idempotency_key or ""
        if key:
            if key in self._seen:
                return None
            self._seen.append(key)
        msg = {
            "id": uuid.uuid4().hex[:12],
            "ts": datetime.now().isoformat(timespec="seconds"),
            "topic": topic,
            "source_agent": source_agent,
            "idempotency_key": key,
            "payload": payload,
        }
        self._log.append(msg)
        for handler in list(self._subs.get(topic, [])) + list(self._subs.get("*", [])):
            try:
                handler(msg)
            except Exception:
                continue
        return msg

    def recent(self, topic: str | None = None, limit: int = 20) -> list[dict]:
        items = list(self._log)
        if topic:
            items = [m for m in items if m.get("topic") == topic]
        return items[-limit:]


bus = AgentBus()
