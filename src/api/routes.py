import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.agents.graph import ANALYST_TOOLS, run_analyst
from src.agents.llm import llm_status
from src.agents.planner import llm_available
from src.agents.researcher import run_researcher, stream_researcher
from src.agents.runner import RESEARCHER_TOOLS, iter_agent, pick_agent
from src.agents.sessions import (
    append_turns,
    create_session,
    get_session,
    history_for_ctx,
    list_sessions,
    session_payload,
)
from src.platform.bus import bus
from src.platform.channels import catalog as channel_catalog
from src.tools.loader import load_manifests
from src.agents.watcher import ensure_jobs, run_watcher
from src.api.deps import current_user
from src.db import get_db
from src.config import settings
from src.db import SessionLocal
from src.market.client import MarketClient, resolve_instruments
from src.market.normalize import infer_market
from src.models import AgentSession, Alert, Artifact, FieldPref, MonitorJob, User, WatchItem
from src.platform.export_xlsx import write_query_xlsx
from src.platform.jobs import job_payload, jobs
from src.platform.pools import catalog, pool_label, resolve_pool
from src.platform.security import issue_token, verify_password
from src.query.engine import QueryEngine
from src.query.registry import registry
from src.tools import registry as tool_registry
from src.tools.base import ToolContext
from src.tools.excel_tools import excel_export

router = APIRouter()
market = MarketClient()
engine = QueryEngine(market)


class LoginIn(BaseModel):
    username: str
    password: str


class WatchIn(BaseModel):
    items: list[dict]


class QueryIn(BaseModel):
    codes: list[str] | None = None
    fields: list[str] | None = None
    pool: str = "watch"
    pool_name: str | None = None
    async_mode: bool = False


class ChatAttachment(BaseModel):
    kind: str = "text"
    name: str = "pasted"
    text: str | None = None
    content_base64: str | None = None
    media_type: str | None = None


class ChatIn(BaseModel):
    question: str = ""
    stream: bool = False
    session_id: int | None = None
    agent: str = "auto"
    attachments: list[ChatAttachment] = []


class AgentExportIn(BaseModel):
    question: str
    answer: str
    cites: list = []
    tools: list = []


class PrefsIn(BaseModel):
    fields: list[str]


class JobToggleIn(BaseModel):
    enabled: bool


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"token": issue_token(user.id, user.username), "username": user.username}


def _tool_ctx(user: User, db: Session) -> ToolContext:
    return ToolContext(user_id=user.id, db=db, market=market, engine=engine)


@router.get("/health")
def health():
    return {
        "ok": True,
        "market": market.health(),
        "agent": {
            "id": "analyst",
            "agents": ["analyst", "watcher", "researcher"],
            "llm": llm_available(),
            "llm_status": llm_status(),
            "tools": [s.id for s in tool_registry.enabled()],
            "analyst_tools": ANALYST_TOOLS,
            "researcher_tools": RESEARCHER_TOOLS,
            "channels": channel_catalog(),
        },
    }


def _watch_payload(item: WatchItem) -> dict:
    suffix = item.code_full.split(".")[-1] if "." in item.code_full else ""
    return {
        "code6": item.code6,
        "code_full": item.code_full,
        "name": item.name,
        "group": item.group_name,
        "market": infer_market(item.code6, suffix),
        "exchange": suffix.upper() if suffix else "",
    }


def _codes_from_items(items: list[dict]) -> tuple[list[str], dict[str, str]]:
    codes = [x.get("code_full") or x.get("code6") or x.get("code") for x in items]
    names = {x.get("code6") or x.get("code"): x.get("name", "") for x in items}
    return codes, names


@router.get("/watchlist")
def get_watchlist(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.query(WatchItem).filter_by(user_id=user.id).all()
    return [_watch_payload(i) for i in items]


@router.put("/watchlist")
def put_watchlist(body: WatchIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    db.query(WatchItem).filter_by(user_id=user.id).delete()
    codes, names = _codes_from_items(body.items)
    insts = resolve_instruments(codes, market)
    saved = []
    for inst in insts:
        item = WatchItem(
            user_id=user.id,
            code6=inst.code6,
            code_full=inst.code_full,
            name=inst.name or names.get(inst.code6, ""),
            group_name="自选",
        )
        db.add(item)
        saved.append(_watch_payload(item))
    db.commit()
    bus.publish("universe.changed", {"user_id": user.id, "count": len(saved)}, "platform")
    return saved


@router.post("/watchlist/items")
def add_watch_items(body: WatchIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    codes, names = _codes_from_items(body.items)
    insts = resolve_instruments(codes, market)
    existing = {i.code6: i for i in db.query(WatchItem).filter_by(user_id=user.id).all()}
    added = []
    for inst in insts:
        if inst.code6 in existing:
            continue
        item = WatchItem(
            user_id=user.id,
            code6=inst.code6,
            code_full=inst.code_full,
            name=inst.name or names.get(inst.code6, ""),
            group_name="自选",
        )
        db.add(item)
        existing[inst.code6] = item
        added.append(_watch_payload(item))
    db.commit()
    items = [_watch_payload(i) for i in existing.values()]
    bus.publish("universe.changed", {"user_id": user.id, "count": len(items)}, "platform")
    return {"added": added, "items": items}


@router.delete("/watchlist/{code6}")
def delete_watch_item(code6: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.query(WatchItem).filter_by(user_id=user.id, code6=code6).first()
    if not item:
        raise HTTPException(status_code=404, detail="自选中没有这只股票")
    db.delete(item)
    db.commit()
    remain = db.query(WatchItem).filter_by(user_id=user.id).all()
    bus.publish("universe.changed", {"user_id": user.id, "count": len(remain)}, "platform")
    return {"removed": code6, "items": [_watch_payload(i) for i in remain]}


@router.get("/markets/instruments")
def instruments(q: str = "", board: str = Query("all", alias="market"), limit: int = 50):
    return market.search(q, board, max(1, min(limit, 200)))


@router.get("/markets/taxonomy")
def market_taxonomy():
    from src.market.futures_map import catalog as futures_catalog
    from src.market.institutions import catalog as institution_catalog
    from src.market.taxonomy import catalog as taxonomy_catalog

    return {
        "taxonomy": taxonomy_catalog(),
        "institutions": institution_catalog(),
        "futures": futures_catalog(),
        "northbound": "未接入",
    }


@router.get("/markets/pools")
def list_pools():
    return {"pools": catalog(), "market": market.health()}


@router.get("/markets/pools/{pool_id:path}/instruments")
def pool_instruments(pool_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    insts, meta = resolve_pool(pool_id, market, user, db)
    return {
        **meta,
        "count": len(insts),
        "items": [
            {
                "code6": i.code6,
                "code_full": i.code_full,
                "name": i.name,
                "market": i.market,
                "exchange": i.exchange,
            }
            for i in insts
        ],
    }


@router.get("/query/fields")
def query_fields():
    return engine.fields()


def _field_view(keys: list[str]) -> list[dict]:
    return [
        {"key": s.key, "label": s.label, "group": s.group}
        for s in registry.all()
        if s.key in keys
    ]


def _user_fields(user: User, db: Session) -> list[str]:
    pref = db.query(FieldPref).filter_by(user_id=user.id).first()
    if pref and pref.field_keys:
        keys = [k for k in json.loads(pref.field_keys) if k in {s.key for s in registry.all()}]
        if keys:
            return keys
    return registry.default_keys()


def _prepare_query(body: QueryIn, user: User, db: Session):
    fields = body.fields or _user_fields(user, db)
    if body.codes:
        insts = resolve_instruments(body.codes, market)
        meta = {"id": "codes", "label": body.pool_name or "筛选一次", "sample": False, "note": ""}
    else:
        insts, meta = resolve_pool(body.pool, market, user, db)
    if not insts:
        raise HTTPException(status_code=400, detail="当前池为空")
    name = body.pool_name or meta["label"]
    return insts, fields, name, meta


def _execute_query(insts, fields: list[str], do_export: bool, pool_name: str, user_id: int) -> dict:
    rows = engine.run(insts, fields)
    codes = [i.code_full for i in insts]
    out = {
        "fields": _field_view(fields),
        "rows": rows,
        "pool": pool_name,
        "count": len(rows),
        "market": market.health(),
    }
    if do_export:
        path = write_query_xlsx(rows, fields, pool_name)
        db = SessionLocal()
        try:
            rec = Artifact(
                user_id=user_id,
                path=str(path),
                filename=path.name,
                pool_name=pool_name,
                field_keys=json.dumps(fields, ensure_ascii=False),
                codes=json.dumps(codes, ensure_ascii=False),
            )
            db.add(rec)
            db.commit()
            out["id"] = rec.id
            out["filename"] = rec.filename
            out["path"] = rec.path
            out["download_url"] = f"/api/artifacts/{rec.id}/download"
        finally:
            db.close()
    return out


def _run_or_enqueue(body: QueryIn, user: User, db: Session, do_export: bool):
    insts, fields, pool_name, meta = _prepare_query(body, user, db)
    use_job = body.async_mode or len(insts) > settings.query_sync_limit
    if not use_job:
        result = _execute_query(insts, fields, do_export, pool_name, user.id)
        result["sample"] = meta.get("sample", False)
        result["note"] = meta.get("note") or ""
        result["pool_id"] = meta.get("id")
        return result
    job = jobs.create("export" if do_export else "query", meta.get("id") or body.pool, len(insts))
    snapshot = list(insts)

    def worker():
        try:
            result = _execute_query(snapshot, fields, do_export, pool_name, user.id)
            result["sample"] = meta.get("sample", False)
            result["note"] = meta.get("note") or ""
            result["pool_id"] = meta.get("id")
            jobs.finish(job.id, result)
        except Exception as exc:
            jobs.fail(job.id, str(exc))

    jobs.spawn(worker)
    return job_payload(job)


@router.post("/query/run")
def query_run(body: QueryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _run_or_enqueue(body, user, db, do_export=False)


@router.post("/query/export")
def query_export(body: QueryIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _run_or_enqueue(body, user, db, do_export=True)


@router.get("/query/jobs/{job_id}")
def query_job(job_id: str, user: User = Depends(current_user)):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return job_payload(job)


@router.get("/artifacts")
def list_artifacts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.query(Artifact).filter_by(user_id=user.id).order_by(Artifact.id.desc()).all()
    return [
        {
            "id": i.id,
            "filename": i.filename,
            "pool_name": i.pool_name,
            "created_at": i.created_at.isoformat() if i.created_at else None,
            "exists": Path(i.path).exists(),
            "download_url": f"/api/artifacts/{i.id}/download",
        }
        for i in items
    ]


@router.get("/artifacts/{art_id}/download")
def download_artifact(art_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rec = db.query(Artifact).filter_by(id=art_id, user_id=user.id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="没有这份档案")
    path = Path(rec.path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="档案文件已丢失")
    return FileResponse(
        path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=rec.filename,
        content_disposition_type="attachment",
    )


@router.get("/agent/tools")
def agent_tools():
    return [
        {
            "id": s.id,
            "name": s.name,
            "kind": s.kind,
            "enabled": s.enabled,
            "reason": s.reason,
        }
        for s in tool_registry.all()
    ]


@router.post("/agent/tools/reload")
def reload_tools():
    return {"loaded": load_manifests()}


@router.get("/agent/sessions")
def agent_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [session_payload(s) for s in list_sessions(db, user)]


@router.get("/agent/sessions/{session_id}")
def agent_session(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = get_session(db, user, session_id)
    if not row:
        raise HTTPException(status_code=404, detail="没有这轮对话")
    return session_payload(row)


@router.get("/agent/bus")
def agent_bus(topic: str = ""):
    return bus.recent(topic or None, limit=30)


@router.post("/agent/chat")
def agent_chat(body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    question = (body.question or "").strip()
    attachments = [a.model_dump() for a in body.attachments if a.text or a.content_base64]
    if not question and not attachments:
        raise HTTPException(status_code=400, detail="请输入问题，或粘贴 / 上传一张表")
    if not question:
        question = "请解析我粘贴的表格，并用接口补全这些股票的行情。"
    agent = pick_agent(question, body.agent)
    row = get_session(db, user, body.session_id) or create_session(db, user, agent, question)
    history = history_for_ctx(row)
    ctx = _tool_ctx(user, db)

    def persist(final: dict) -> dict:
        store = SessionLocal()
        try:
            current = store.get(AgentSession, row.id) or create_session(store, user, agent, question)
            append_turns(
                store,
                current,
                [
                    {"role": "user", "content": question},
                    {
                        "role": "assistant",
                        "content": final.get("answer") or "",
                        "cites": final.get("cites") or [],
                        "tools": final.get("tools") or [],
                        "agent": final.get("agent") or agent,
                    },
                ],
                agent=final.get("agent") or agent,
            )
            sid = current.id
        finally:
            store.close()
        out = {**final, "session_id": sid}
        bus.publish("ask.answer", {"session_id": sid, "agent": out["agent"]}, out["agent"])
        return out

    if not body.stream:
        result = run_researcher(question, ctx, attachments, history) if agent == "researcher" else run_analyst(question, ctx, attachments, history)
        return persist(result)

    def events():
        final = {"answer": "", "cites": [], "tools": [], "agent": agent}
        stream = (
            stream_researcher(question, ctx, attachments, history)
            if agent == "researcher"
            else iter_agent(question, ctx, agent=agent, attachments=attachments, history=history, stream_tokens=True)
        )
        for ev in stream:
            if ev.get("type") == "done":
                final = ev
                continue
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
        done = persist(final)
        yield f"data: {json.dumps({'type': 'done', **done}, ensure_ascii=False)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream")


@router.post("/agent/export")
def agent_export(body: AgentExportIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = excel_export(
        {
            "question": body.question,
            "answer": body.answer,
            "cites": body.cites,
            "tools": body.tools,
        },
        _tool_ctx(user, db),
    )
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error or "导出失败")
    data = result.data or {}
    if data.get("id"):
        data["download_url"] = f"/api/artifacts/{data['id']}/download"
    return data


@router.get("/query/prefs")
def get_prefs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"fields": _user_fields(user, db), "all": engine.fields()}


@router.put("/query/prefs")
def put_prefs(body: PrefsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    allowed = {s.key for s in registry.all()}
    keys = [k for k in body.fields if k in allowed]
    if not keys:
        raise HTTPException(status_code=400, detail="至少保留一列")
    pref = db.query(FieldPref).filter_by(user_id=user.id).first()
    payload = json.dumps(keys, ensure_ascii=False)
    if pref:
        pref.field_keys = payload
    else:
        db.add(FieldPref(user_id=user.id, field_keys=payload))
    db.commit()
    return {"fields": keys}


@router.get("/monitor/jobs")
def list_jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    jobs_list = ensure_jobs(db, user)
    return [
        {
            "id": j.id,
            "job_key": j.job_key,
            "name": j.name,
            "enabled": bool(j.enabled),
            "reason": j.reason,
        }
        for j in jobs_list
    ]


@router.post("/monitor/jobs/{job_key}/toggle")
def toggle_job(job_key: str, body: JobToggleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_jobs(db, user)
    job = db.query(MonitorJob).filter_by(user_id=user.id, job_key=job_key).first()
    if not job:
        raise HTTPException(status_code=404, detail="没有这个监控项")
    if job.reason and body.enabled:
        raise HTTPException(status_code=409, detail=job.reason)
    job.enabled = 1 if body.enabled else 0
    db.commit()
    return {"job_key": job.job_key, "enabled": bool(job.enabled)}


@router.post("/monitor/jobs/{job_key}/run")
def run_one_job(job_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_jobs(db, user)
    return run_watcher(db, user, market, job_key)


@router.post("/monitor/run")
def run_all_jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return run_watcher(db, user, market)


@router.get("/alerts")
def list_alerts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.query(Alert).filter_by(user_id=user.id).order_by(Alert.id.desc()).limit(50).all()
    return [
        {
            "id": i.id,
            "job_key": i.job_key,
            "code6": i.code6,
            "title": i.title,
            "detail": i.detail,
            "created_at": i.created_at.isoformat() if i.created_at else None,
        }
        for i in items
    ]
