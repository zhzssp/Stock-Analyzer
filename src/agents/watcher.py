from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from src.market.client import MarketClient, resolve_instruments
from src.models import Alert, MonitorJob, Snapshot, User, WatchItem
from src.query.engine import QueryEngine
from src.tools import registry
from src.tools.base import ToolContext


JOB_DEFS = [
    {"job_key": "holders-change", "name": "股东变动", "enabled": 1, "reason": ""},
    {"job_key": "capital-flow", "name": "资金异常", "enabled": 1, "reason": ""},
    {"job_key": "corp-events", "name": "分红 / 增发 / 解禁", "enabled": 1, "reason": ""},
    {"job_key": "near-bottom", "name": "接近底部", "enabled": 1, "reason": ""},
    {"job_key": "futures", "name": "期货联动", "enabled": 0, "reason": "等待期货 Tool"},
    {"job_key": "news", "name": "资讯冲击", "enabled": 0, "reason": "等待检索 Tool"},
    {"job_key": "policy", "name": "产业政策 / 基金调仓", "enabled": 0, "reason": "等待资讯 Tool"},
]


def ensure_jobs(db: Session, user: User) -> list[MonitorJob]:
    existing = {j.job_key: j for j in db.query(MonitorJob).filter_by(user_id=user.id).all()}
    for spec in JOB_DEFS:
        if spec["job_key"] in existing:
            continue
        job = MonitorJob(user_id=user.id, **spec)
        db.add(job)
        existing[spec["job_key"]] = job
    db.commit()
    return list(existing.values())


def _snap(db: Session, user_id: int, code6: str, kind: str) -> Snapshot | None:
    return db.query(Snapshot).filter_by(user_id=user_id, code6=code6, kind=kind).first()


def _write_snap(db: Session, user_id: int, code6: str, kind: str, payload: dict) -> None:
    row = _snap(db, user_id, code6, kind)
    text = json.dumps(payload, ensure_ascii=False)
    if row:
        row.payload = text
    else:
        db.add(Snapshot(user_id=user_id, code6=code6, kind=kind, payload=text))


def _today_dup(db: Session, user_id: int, job_key: str, code6: str) -> bool:
    start = datetime.combine(date.today(), datetime.min.time())
    return (
        db.query(Alert)
        .filter(
            Alert.user_id == user_id,
            Alert.job_key == job_key,
            Alert.code6 == code6,
            Alert.created_at >= start,
        )
        .first()
        is not None
    )


def _alert(db: Session, user_id: int, job_key: str, code6: str, title: str, detail: str) -> Alert | None:
    if _today_dup(db, user_id, job_key, code6):
        return None
    rec = Alert(user_id=user_id, job_key=job_key, code6=code6, title=title, detail=detail)
    db.add(rec)
    return rec


def _ctx(db: Session, user: User, market: MarketClient) -> ToolContext:
    return ToolContext(user_id=user.id, db=db, market=market, engine=QueryEngine(market))


def _row(ctx: ToolContext, tool_id: str, inst, extra: dict | None = None):
    args = {"code": inst.code_full}
    if extra:
        args.update(extra)
    result = registry.run(tool_id, args, ctx)
    if not result.ok:
        return None
    data = result.data
    if isinstance(data, dict) and isinstance(data.get("rows"), list):
        data = data["rows"]
    if isinstance(data, list):
        return data[0] if data else None
    return data


def run_watcher(db: Session, user: User, market: MarketClient, job_key: str | None = None) -> dict:
    ensure_jobs(db, user)
    jobs = db.query(MonitorJob).filter_by(user_id=user.id).all()
    if job_key:
        jobs = [j for j in jobs if j.job_key == job_key]
    items = db.query(WatchItem).filter_by(user_id=user.id).all()
    insts = resolve_instruments([i.code_full for i in items], market)
    ctx = _ctx(db, user, market)
    hits: list[dict] = []
    for job in jobs:
        if not job.enabled:
            continue
        for inst in insts:
            hit = None
            if job.job_key == "holders-change":
                hit = _rule_holders(db, user, ctx, inst)
            elif job.job_key == "capital-flow":
                hit = _rule_flow(db, user, ctx, inst)
            elif job.job_key == "corp-events":
                hit = _rule_events(db, user, ctx, inst)
            elif job.job_key == "near-bottom":
                hit = _rule_bottom(db, user, ctx, inst)
            if hit:
                hits.append(hit)
    db.commit()
    from src.platform.bus import bus

    for hit in hits:
        bus.publish(
            "watch.hit",
            {**hit, "user_id": user.id},
            source_agent="watcher",
            idempotency_key=f"{user.id}:{hit.get('job_key')}:{hit.get('code6')}:{date.today().isoformat()}",
        )
    bus.publish(
        "watch.digest",
        {"user_id": user.id, "count": len(hits), "ran": [j.job_key for j in jobs if j.enabled]},
        source_agent="watcher",
        idempotency_key=f"{user.id}:digest:{date.today().isoformat()}:{job_key or 'all'}",
    )
    return {"ran": [j.job_key for j in jobs if j.enabled], "hits": hits, "count": len(hits)}


def _rule_holders(db: Session, user: User, ctx: ToolContext, inst) -> dict | None:
    row = _row(ctx, "holders_flow", inst)
    cur = (row or {}).get("holders") or ""
    prev = _snap(db, user.id, inst.code6, "holders")
    old = json.loads(prev.payload or "{}").get("holders") if prev else None
    _write_snap(db, user.id, inst.code6, "holders", {"holders": cur})
    if old is None:
        return None
    if old == cur or not cur:
        return None
    rec = _alert(db, user.id, "holders-change", inst.code6, f"{inst.name} · 十大流通股东变动", f"{old} → {cur}")
    return {"job_key": "holders-change", "code6": inst.code6, "title": rec.title} if rec else None


def _rule_flow(db: Session, user: User, ctx: ToolContext, inst) -> dict | None:
    row = _row(ctx, "capital_flow", inst)
    if not row:
        return None
    latest, mean = row.get("latest_net"), row.get("mean_net")
    if latest is None or mean is None or latest <= mean * 2:
        return None
    rec = _alert(
        db,
        user.id,
        "capital-flow",
        inst.code6,
        f"{inst.name} · 资金净流入偏离",
        f"最新 {latest:.0f}，近窗均值 {mean:.0f}",
    )
    return {"job_key": "capital-flow", "code6": inst.code6, "title": rec.title} if rec else None


def _rule_events(db: Session, user: User, ctx: ToolContext, inst) -> dict | None:
    row = _row(ctx, "corp_events", inst)
    if not row:
        return None
    bits = []
    for item in row.get("dividends") or []:
        bits.append(item.get("name") or item.get("date") or "分红")
    for item in row.get("seo") or []:
        bits.append(item.get("name") or "增发")
    for item in row.get("unlock") or []:
        bits.append(item.get("name") or "解禁")
    if not bits:
        return None
    fingerprint = "、".join(str(b) for b in bits)
    prev = _snap(db, user.id, inst.code6, "events")
    old = json.loads(prev.payload or "{}").get("text") if prev else None
    _write_snap(db, user.id, inst.code6, "events", {"text": fingerprint})
    if old == fingerprint:
        return None
    rec = _alert(db, user.id, "corp-events", inst.code6, f"{inst.name} · 公司事件", fingerprint)
    return {"job_key": "corp-events", "code6": inst.code6, "title": rec.title} if rec else None


def _rule_bottom(db: Session, user: User, ctx: ToolContext, inst) -> dict | None:
    row = _row(ctx, "bottom", inst)
    if not row:
        return None
    off = row.get("off_low")
    if off is None or off > 8:
        return None
    rec = _alert(
        db,
        user.id,
        "near-bottom",
        inst.code6,
        f"{inst.name} · 接近底部",
        f"现价 {row.get('price')}，离长窗底 {off}%（{row.get('note')}）",
    )
    return {"job_key": "near-bottom", "code6": inst.code6, "title": rec.title} if rec else None
