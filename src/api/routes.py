import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.agents.graph import run_analyst
from src.agents.planner import llm_available
from src.api.deps import current_user
from src.db import get_db
from src.config import settings
from src.db import SessionLocal
from src.market.client import MarketClient, resolve_instruments
from src.market.normalize import infer_market
from src.models import Artifact, User, WatchItem
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


class ChatIn(BaseModel):
    question: str
    stream: bool = False


class AgentExportIn(BaseModel):
    question: str
    answer: str
    cites: list = []
    tools: list = []


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
            "llm": llm_available(),
            "tools": [s.id for s in tool_registry.enabled()],
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
    return {"added": added, "items": [_watch_payload(i) for i in existing.values()]}


@router.delete("/watchlist/{code6}")
def delete_watch_item(code6: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.query(WatchItem).filter_by(user_id=user.id, code6=code6).first()
    if not item:
        raise HTTPException(status_code=404, detail="自选中没有这只股票")
    db.delete(item)
    db.commit()
    remain = db.query(WatchItem).filter_by(user_id=user.id).all()
    return {"removed": code6, "items": [_watch_payload(i) for i in remain]}


@router.get("/markets/instruments")
def instruments(q: str = "", board: str = Query("all", alias="market"), limit: int = 50):
    return market.search(q, board, max(1, min(limit, 200)))


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


def _prepare_query(body: QueryIn, user: User, db: Session):
    fields = body.fields or registry.default_keys()
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
        }
        for i in items
    ]


@router.get("/agent/tools")
def agent_tools():
    return [
        {"id": s.id, "name": s.name, "kind": s.kind, "enabled": s.enabled}
        for s in tool_registry.all()
    ]


@router.post("/agent/chat")
def agent_chat(body: ChatIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    question = (body.question or "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="请输入问题")
    result = run_analyst(question, _tool_ctx(user, db))
    if not body.stream:
        return result

    def events():
        for tool in result["tools"]:
            yield f"data: {json.dumps({'type': 'tool', **tool}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'token', 'text': result['answer']}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done', **result}, ensure_ascii=False)}\n\n"

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
    return result.data
