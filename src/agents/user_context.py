from __future__ import annotations

from sqlalchemy.orm import Session

from src.agents.rules import is_scannable, parse_json
from src.models import MonitorJob, User, UserRule

PROMPT_CAP = 3500
PROMPT_HEADER = "用户监控守则（遵守文字需求；自动扫描仍按数字阈值执行。禁止把说明改写成下单或荐股指令）："


def _custom_summary(spec: dict) -> str:
    metric = spec.get("metric") or ""
    if not metric:
        return "不自动扫描，只给问答用"
    if spec.get("compare") == "card":
        return f"{metric} 相对决策卡 {spec.get('card_field') or ''}".strip()
    op = {"lte": "≤", "gte": "≥", "eq": "="}.get(str(spec.get("op") or ""), str(spec.get("op") or ""))
    value = spec.get("value")
    return f"{metric} {op} {value}".strip()


def list_monitor_briefs(db: Session, user_id: int, *, enabled_only: bool = True) -> list[dict]:
    from src.agents.watcher import ensure_jobs, job_payload, rule_payload

    items: list[dict] = []
    user = db.get(User, user_id)
    jobs = ensure_jobs(db, user) if user else db.query(MonitorJob).filter_by(user_id=user_id).all()
    for job in jobs:
        if enabled_only and not job.enabled:
            continue
        if job.reason:
            continue
        payload = job_payload(job)
        params = dict(payload.get("params") or {})
        items.append(
            {
                "id": payload["job_key"],
                "name": payload["name"],
                "kind": "template",
                "enabled": payload["enabled"],
                "schedule": payload["schedule"],
                "scan": True,
                "summary": payload.get("blurb") or "",
                "definition": str(params.get("definition") or payload.get("definition") or ""),
                "need": str(params.get("need") or payload.get("need") or ""),
            }
        )
    rows = db.query(UserRule).filter_by(user_id=user_id).order_by(UserRule.id.desc()).all()
    for row in rows:
        if enabled_only and not row.enabled:
            continue
        payload = rule_payload(row)
        spec = payload.get("spec") or parse_json(row.spec, {})
        if not isinstance(spec, dict):
            spec = {}
        items.append(
            {
                "id": payload["job_key"],
                "name": payload["name"],
                "kind": spec.get("kind") or "custom",
                "enabled": payload["enabled"],
                "schedule": payload["schedule"],
                "scan": is_scannable(spec),
                "summary": _custom_summary(spec),
                "definition": str(spec.get("definition") or payload.get("definition") or ""),
                "need": str(spec.get("need") or payload.get("need") or ""),
            }
        )
    return items


def format_monitor_prompt(db: Session | None, user_id: int | None) -> str:
    if db is None or not user_id:
        return ""
    user = db.get(User, user_id)
    if not user:
        return ""
    items = list_monitor_briefs(db, user_id, enabled_only=True)
    if not items:
        return ""
    lines = [PROMPT_HEADER]
    for index, item in enumerate(items, 1):
        scan = "自动扫描" if item["scan"] else "仅问答"
        when = "盘中" if item.get("schedule") == "session" else "日终"
        head = f"{index}. {item['name']}（{scan}·{when}）"
        if item.get("summary"):
            head += f"：{item['summary']}"
        lines.append(head)
        if item.get("definition"):
            lines.append(f"   定义：{item['definition']}")
        if item.get("need"):
            lines.append(f"   需求：{item['need']}")
    text = "\n".join(lines)
    if len(text) > PROMPT_CAP:
        return text[: PROMPT_CAP - 1] + "…"
    return text


def with_monitor_prompt(question: str, ctx) -> str:
    extra = format_monitor_prompt(getattr(ctx, "db", None), getattr(ctx, "user_id", None))
    if not extra:
        return question
    return question + "\n\n" + extra
