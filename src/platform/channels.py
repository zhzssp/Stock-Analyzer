from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from src.config import settings
from src.platform.bus import bus

log = logging.getLogger("stock.channels")


def _log_file() -> Path:
    path = settings.data_dir / "alerts.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def notify_log(msg: dict) -> None:
    line = json.dumps(msg, ensure_ascii=False)
    log.info("%s %s", msg.get("topic"), msg.get("id"))
    _log_file().open("a", encoding="utf-8").write(line + "\n")


def notify_webhook(msg: dict) -> None:
    url = (settings.alert_webhook or "").strip()
    if not url:
        return
    try:
        httpx.post(url, json=msg, timeout=5.0)
    except Exception:
        return


def on_watch_event(msg: dict) -> None:
    notify_log(msg)
    if msg.get("topic") in {"watch.hit", "watch.digest"}:
        notify_webhook(msg)


_attached = False


def attach() -> None:
    global _attached
    if _attached:
        return
    bus.subscribe("watch.hit", on_watch_event)
    bus.subscribe("watch.digest", on_watch_event)
    bus.subscribe("universe.changed", on_watch_event)
    _attached = True


def catalog() -> list[dict]:
    return [
        {"id": "log", "name": "本机日志", "enabled": True, "reason": ""},
        {"id": "desktop", "name": "监控中心列表", "enabled": True, "reason": "命中已写入 alerts"},
        {
            "id": "webhook",
            "name": "Webhook",
            "enabled": bool((settings.alert_webhook or "").strip()),
            "reason": "" if (settings.alert_webhook or "").strip() else "未配置 ALERT_WEBHOOK",
        },
    ]
