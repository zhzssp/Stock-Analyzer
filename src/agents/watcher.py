from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy.orm import Session

from src.agents.rules import (
    JOB_DEFS,
    TEMPLATE_SPECS,
    eval_custom,
    eval_near_bottom,
    eval_near_target,
    in_scope,
    merge_params,
    parse_json,
    validate_custom_spec,
)
from src.market.client import MarketClient, resolve_instruments
from src.market.holders_diff import diff_holders, format_diff, normalize_holders, watch_hits
from src.models import Alert, MonitorJob, Snapshot, User, UserRule, WatchItem
from src.platform.monitor_prefs import institution_catalog_for
from src.query.cards import card_dict
from src.query.engine import QueryEngine
from src.query.registry import registry as field_registry
from src.tools import registry
from src.tools.base import ToolContext


def ensure_jobs(db: Session, user: User) -> list[MonitorJob]:
    existing = {j.job_key: j for j in db.query(MonitorJob).filter_by(user_id=user.id).all()}
    for spec in JOB_DEFS:
        job = existing.get(spec["job_key"])
        if job:
            if not job.kind:
                job.kind = "template"
            if not job.schedule:
                job.schedule = spec.get("schedule") or "eod"
            if not job.severity:
                job.severity = spec.get("severity") or "watch"
            if not job.params:
                job.params = json.dumps(spec.get("params") or {}, ensure_ascii=False)
            continue
        job = MonitorJob(
            user_id=user.id,
            job_key=spec["job_key"],
            name=spec["name"],
            enabled=spec["enabled"],
            reason=spec["reason"],
            params=json.dumps(spec.get("params") or {}, ensure_ascii=False),
            kind="template",
            schedule=spec.get("schedule") or "eod",
            severity=spec.get("severity") or "watch",
        )
        db.add(job)
        existing[spec["job_key"]] = job
    db.commit()
    return list(existing.values())


def job_payload(job: MonitorJob) -> dict:
    spec = TEMPLATE_SPECS.get(job.job_key) or {}
    params = merge_params(job.job_key, job.params)
    return {
        "id": job.id,
        "job_key": job.job_key,
        "name": job.name,
        "enabled": bool(job.enabled),
        "reason": job.reason,
        "kind": job.kind or "template",
        "schedule": job.schedule or spec.get("schedule") or "eod",
        "severity": job.severity or spec.get("severity") or "watch",
        "params": params,
        "schema": spec.get("schema") or [],
        "blurb": spec.get("blurb") or "",
    }


def rule_payload(row: UserRule) -> dict:
    spec = parse_json(row.spec, {})
    return {
        "id": row.id,
        "job_key": f"custom:{row.id}",
        "name": row.name,
        "enabled": bool(row.enabled),
        "kind": "custom",
        "spec": spec,
        "schedule": spec.get("schedule") or "eod",
        "severity": spec.get("severity") or "watch",
    }


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


def _alert(
    db: Session,
    user_id: int,
    job_key: str,
    code6: str,
    title: str,
    detail: str,
    *,
    persist: bool,
    severity: str = "watch",
    rule_id: str = "",
) -> dict | None:
    payload = {
        "job_key": job_key,
        "rule_id": rule_id or job_key,
        "code6": code6,
        "title": title,
        "detail": detail,
        "severity": severity,
    }
    if not persist:
        return payload
    if _today_dup(db, user_id, job_key, code6):
        return None
    rec = Alert(
        user_id=user_id,
        job_key=job_key,
        code6=code6,
        title=title,
        detail=detail,
        status="open",
        severity=severity,
        rule_id=rule_id or job_key,
    )
    db.add(rec)
    return payload


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


def _cards(items: list[WatchItem]) -> dict[str, dict]:
    return {i.code6: card_dict(i) for i in items}


def _query_rows(ctx: ToolContext, insts, items: list[WatchItem], keys: list[str]) -> dict[str, dict]:
    rows = ctx.engine.run(insts, keys, cards=_cards(items))
    return {r["code6"]: r for r in rows}


def run_watcher(
    db: Session,
    user: User,
    market: MarketClient,
    job_key: str | None = None,
    schedule: str | None = None,
    persist: bool = True,
    preview_spec: dict | None = None,
) -> dict:
    ensure_jobs(db, user)
    jobs = db.query(MonitorJob).filter_by(user_id=user.id).all()
    customs = db.query(UserRule).filter_by(user_id=user.id).all()
    if preview_spec is not None:
        jobs = []
        customs = []
    elif job_key:
        if job_key.startswith("custom:"):
            try:
                rid = int(job_key.split(":", 1)[1])
            except ValueError:
                jobs = []
                customs = []
            else:
                jobs = []
                customs = [r for r in customs if r.id == rid]
        else:
            jobs = [j for j in jobs if j.job_key == job_key]
            customs = []
    elif schedule:
        jobs = [j for j in jobs if (j.schedule or (TEMPLATE_SPECS.get(j.job_key) or {}).get("schedule") or "eod") == schedule]
        customs = [r for r in customs if (parse_json(r.spec, {}).get("schedule") or "eod") == schedule]
    items = db.query(WatchItem).filter_by(user_id=user.id).all()
    insts = resolve_instruments([i.code_full for i in items], market)
    inst_by_code = {i.code6: i for i in insts}
    ctx = _ctx(db, user, market)
    catalog = institution_catalog_for(db, user.id)
    hits: list[dict] = []
    needed = {"price", "off_low", "target", "low_note", "reduce_at", "buy_low", "buy_high", "dist_buy", "dist_reduce", "vs_cost", "cost"}
    custom_specs: list[tuple[UserRule | None, dict]] = []
    if preview_spec is not None:
        custom_specs.append((None, validate_custom_spec(preview_spec)))
        needed.add(custom_specs[0][1]["metric"])
    else:
        for row in customs:
            if not row.enabled and job_key is None:
                continue
            if not row.enabled:
                continue
            try:
                spec = validate_custom_spec(parse_json(row.spec, {}))
            except ValueError:
                continue
            custom_specs.append((row, spec))
            needed.add(spec["metric"])

    query_keys = [k for k in needed if k in {s.key for s in field_registry.all()}]
    if "low_note" not in query_keys:
        query_keys.append("low_note")
    rows_by_code = _query_rows(ctx, insts, items, query_keys) if insts else {}

    for job in jobs:
        if job.reason:
            continue
        if not job.enabled:
            continue
        params = merge_params(job.job_key, job.params)
        scoped_items = [i for i in items if in_scope(i, params)]
        for item in scoped_items:
            inst = inst_by_code.get(item.code6)
            if not inst:
                continue
            hit = None
            if job.job_key == "holders-change":
                hit = _rule_holders(db, user, ctx, inst, params, catalog, persist)
            elif job.job_key == "fund-holding":
                hit = _rule_funds(db, user, ctx, inst, persist)
            elif job.job_key == "capital-flow":
                hit = _rule_flow(db, user, ctx, inst, params, persist)
            elif job.job_key == "corp-events":
                hit = _rule_events(db, user, ctx, inst, params, persist)
            elif job.job_key == "near-bottom":
                ok, detail = eval_near_bottom(rows_by_code.get(item.code6) or {}, params)
                if ok:
                    hit = _alert(
                        db,
                        user.id,
                        "near-bottom",
                        inst.code6,
                        f"{inst.name} · 接近底部",
                        detail,
                        persist=persist,
                        severity=job.severity or "act",
                    )
            elif job.job_key == "near-target":
                ok, detail = eval_near_target(rows_by_code.get(item.code6) or {}, params)
                if ok:
                    hit = _alert(
                        db,
                        user.id,
                        "near-target",
                        inst.code6,
                        f"{inst.name} · 接近减仓",
                        detail,
                        persist=persist,
                        severity=job.severity or "act",
                    )
            if hit:
                hits.append(hit)

    for row, spec in custom_specs:
        job_key_custom = f"custom:{row.id}" if row else "custom:preview"
        name = (row.name if row else spec.get("name")) or "自定义规则"
        severity = spec.get("severity") or "watch"
        scoped_items = [i for i in items if in_scope(i, spec)]
        for item in scoped_items:
            inst = inst_by_code.get(item.code6)
            if not inst:
                continue
            qrow = rows_by_code.get(item.code6) or {}
            ok, detail = eval_custom(qrow, spec)
            if not ok:
                continue
            title = spec.get("title_template") or f"{inst.name} · {name}"
            hit = _alert(
                db,
                user.id,
                job_key_custom,
                inst.code6,
                title,
                detail,
                persist=persist and row is not None,
                severity=severity,
                rule_id=job_key_custom,
            )
            if hit:
                hits.append(hit)

    if persist:
        db.commit()
        from src.platform.bus import bus

        for hit in hits:
            bus.publish(
                "watch.hit",
                {**hit, "user_id": user.id},
                source_agent="watcher",
                idempotency_key=f"{user.id}:{hit.get('job_key')}:{hit.get('code6')}:{date.today().isoformat()}",
            )
        ran = [j.job_key for j in jobs if j.enabled and not j.reason]
        ran += [f"custom:{r.id}" for r, _ in custom_specs if r]
        bus.publish(
            "watch.digest",
            {"user_id": user.id, "count": len(hits), "ran": ran},
            source_agent="watcher",
            idempotency_key=f"{user.id}:digest:{date.today().isoformat()}:{job_key or schedule or 'all'}",
        )
    else:
        ran = [j.job_key for j in jobs if j.enabled and not j.reason]
        ran += ["custom:preview"] if preview_spec is not None else [f"custom:{r.id}" for r, _ in custom_specs if r]
    return {"ran": ran, "hits": hits, "count": len(hits)}


def _holder_items(row: dict | None, catalog: list[dict] | None) -> list[dict]:
    if not row:
        return []
    detail = row.get("top_holders_detail") or row.get("holders_detail") or []
    if detail:
        return normalize_holders(detail, catalog)
    names = [p.strip() for p in str(row.get("holders") or "").split("、") if p.strip()]
    return [{"name": n, "shares": None, "pct": None} for n in names]


def _rule_holders(db, user, ctx, inst, params: dict, catalog: list[dict], persist: bool) -> dict | None:
    row = _row(ctx, "holders_flow", inst)
    cur_items = _holder_items(row, catalog)
    prev = _snap(db, user.id, inst.code6, "holders")
    old_payload = json.loads(prev.payload) if prev and prev.payload else {}
    old_items = old_payload.get("items")
    if old_items is None and old_payload.get("holders"):
        old_items = [{"name": p, "shares": None, "pct": None} for p in str(old_payload["holders"]).split("、") if p]
    if persist:
        _write_snap(db, user.id, inst.code6, "holders", {"items": cur_items, "holders": (row or {}).get("holders") or ""})
    if old_items is None:
        return None
    diff = diff_holders(old_items, cur_items)
    if not diff["changed"]:
        return None
    watched = watch_hits(diff)
    mode = params.get("mode") or "any"
    if mode == "watch_only" and not watched:
        return None
    detail = format_diff(diff)
    if params.get("highlight_watch", True) and watched:
        detail = "重点机构 " + "、".join(x.get("institution") or x.get("name") for x in watched) + "。 " + detail
    return _alert(db, user.id, "holders-change", inst.code6, f"{inst.name} · 十大股东变动", detail, persist=persist)


def _rule_funds(db, user, ctx, inst, persist: bool) -> dict | None:
    result = registry.run("fund_holding", {"code": inst.code_full}, ctx)
    if not result.ok:
        return None
    rows = result.data if isinstance(result.data, list) else []
    row = rows[0] if rows else {}
    hits = row.get("watch_hits") or []
    names = [h.get("name") for h in hits if h.get("name")]
    fingerprint = "、".join(names)
    prev = _snap(db, user.id, inst.code6, "funds")
    old = json.loads(prev.payload or "{}").get("text") if prev else None
    if persist:
        _write_snap(db, user.id, inst.code6, "funds", {"text": fingerprint})
    if not names or old == fingerprint:
        return None
    return _alert(db, user.id, "fund-holding", inst.code6, f"{inst.name} · 活跃资金持股", fingerprint, persist=persist)


def _rule_flow(db, user, ctx, inst, params: dict, persist: bool) -> dict | None:
    row = _row(ctx, "capital_flow", inst)
    if not row:
        return None
    latest, mean = row.get("latest_net"), row.get("mean_net")
    multiple = float(params.get("mean_multiple") or 2)
    if latest is None or mean is None or latest <= mean * multiple:
        return None
    detail = f"流入 {row.get('inflow')} 流出 {row.get('outflow')} 净流入 {latest:.0f}，近窗均值 {mean:.0f}"
    return _alert(db, user.id, "capital-flow", inst.code6, f"{inst.name} · 资金净流入偏离", detail, persist=persist)


def _rule_events(db, user, ctx, inst, params: dict, persist: bool) -> dict | None:
    row = _row(ctx, "corp_events", inst)
    if not row:
        return None
    bits = []
    if params.get("dividends", True):
        for item in row.get("dividends") or []:
            bits.append(item.get("name") or item.get("date") or "分红")
    if params.get("seo", True):
        for item in row.get("seo") or []:
            bits.append(item.get("name") or "增发")
    if params.get("unlock", True):
        for item in row.get("unlock") or []:
            bits.append(item.get("name") or "解禁")
    if not bits:
        return None
    fingerprint = "、".join(str(b) for b in bits)
    prev = _snap(db, user.id, inst.code6, "events")
    old = json.loads(prev.payload or "{}").get("text") if prev else None
    if persist:
        _write_snap(db, user.id, inst.code6, "events", {"text": fingerprint})
    if old == fingerprint:
        return None
    link = row.get("cninfo_url") or ""
    if link:
        fingerprint = f"{fingerprint}；公告 {link}"
    return _alert(db, user.id, "corp-events", inst.code6, f"{inst.name} · 公司事件", fingerprint, persist=persist)
