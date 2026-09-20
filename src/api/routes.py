import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from src.agents.graph import run_analyst
from src.agents.llm import llm_status
from src.agents.planner import llm_available
from src.agents.policy import policies_public, reload_policies, tools_for
from src.agents.queue import today_queue
from src.agents.reviewer import REVIEW_LABELS, reviews_payload, run_reviewer
from src.agents.researcher import run_researcher, stream_researcher
from src.agents.rules import GROUPS, clip_note, metric_specs, validate_custom_spec
from src.agents.runner import iter_agent, pick_agent
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
from src.agents.watcher import ensure_jobs, job_payload, rule_payload, run_watcher
from src.api.deps import current_user
from src.db import get_db
from src.config import settings
from src.db import SessionLocal
from src.market.client import MarketClient, resolve_instruments
from src.market.clock import (
    clock_series,
    configured_clock_dir,
    list_slots,
    load_slot,
    set_clock_dir,
    status as clock_status,
    write_universe,
)
from src.market.normalize import infer_market
from src.models import AgentSession, Alert, Artifact, FieldPref, MonitorJob, MonitorPref, User, UserRule, WatchItem
from src.platform.export_xlsx import write_query_xlsx
from src.platform.jobs import job_payload as bg_job_payload, jobs
from src.platform.monitor_prefs import pref_payload
from src.platform.pools import catalog, resolve_pool
from src.platform.security import issue_token, verify_password
from src.platform.storage import clear_cache, enforce_all, health_storage, prune_artifacts, record_artifact, usage
from src.query.cards import card_dict
from src.query.engine import QueryEngine
from src.query.registry import registry
from src.tools import registry as tool_registry
from src.tools.base import ToolContext, ToolResult
from src.tools.excel_tools import excel_diff, excel_export, excel_read
from src.tools.research_tools import export_share
from src.tools.warehouse_tools import warehouse_get

router = APIRouter()
market = MarketClient()
engine = QueryEngine(market)


class LoginIn(BaseModel):
    username: str
    password: str


class WatchIn(BaseModel):
    items: list[dict]


class WatchOrderIn(BaseModel):
    codes: list[str]


class QueryIn(BaseModel):
    codes: list[str] | None = None
    fields: list[str] | None = None
    pool: str = "watch"
    pool_name: str | None = None
    async_mode: bool = False


class DiffIn(BaseModel):
    id_a: int | None = None
    id_b: int | None = None
    column: str | None = None


class ClockDirIn(BaseModel):
    path: str


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


class JobPatchIn(BaseModel):
    enabled: bool | None = None
    params: dict | None = None
    schedule: str | None = None


class CardIn(BaseModel):
    thesis: str = ""
    cost: float | None = None
    shares: float | None = None
    buy_low: float | None = None
    buy_high: float | None = None
    reduce_price: float | None = None
    invalid_if: str = ""
    group: str | None = None


class RuleIn(BaseModel):
    name: str = ""
    enabled: bool = True
    spec: dict = {}


class AlertPatchIn(BaseModel):
    status: str


class MonitorPrefIn(BaseModel):
    selected: list[str] = []
    custom: list[dict] = []


class PreviewIn(BaseModel):
    spec: dict | None = None
    job_key: str | None = None
    persist: bool = False


@router.post("/auth/login")
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter_by(username=body.username).first()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"token": issue_token(user.id, user.username), "username": user.username}


def _tool_ctx(user: User, db: Session) -> ToolContext:
    return ToolContext(user_id=user.id, db=db, market=market, engine=engine)


def _tool_http(result: ToolResult) -> dict:
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.error or "工具失败")
    return result.to_dict()


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
            "analyst_tools": tools_for("analyst"),
            "researcher_tools": tools_for("researcher"),
            "channels": channel_catalog(),
            "policies": policies_public(),
        },
        "storage": health_storage(),
        "clock": clock_status(),
    }


def _watch_payload(item: WatchItem) -> dict:
    suffix = item.code_full.split(".")[-1] if "." in item.code_full else ""
    card = card_dict(item)
    filled = bool(
        card.get("thesis")
        or card.get("cost") is not None
        or card.get("buy_low") is not None
        or card.get("buy_high") is not None
        or card.get("reduce_price") is not None
        or card.get("invalid_if")
    )
    return {
        "code6": item.code6,
        "code_full": item.code_full,
        "name": item.name,
        "group": item.group_name,
        "market": infer_market(item.code6, suffix),
        "exchange": suffix.upper() if suffix else "",
        "card": card,
        "card_filled": filled,
        "sort_order": int(getattr(item, "sort_order", 0) or 0),
    }


def _cards_map(db: Session, user: User) -> dict[str, dict]:
    return {i.code6: card_dict(i) for i in db.query(WatchItem).filter_by(user_id=user.id).all()}


def _sync_clock_universe(user: User, db: Session) -> None:
    root = configured_clock_dir()
    if root is None:
        return
    codes = [i.code6 for i in db.query(WatchItem).filter_by(user_id=user.id).all()]
    write_universe(root, user.username, codes)


def _watch_ordered(db: Session, user: User) -> list[WatchItem]:
    return (
        db.query(WatchItem)
        .filter_by(user_id=user.id)
        .order_by(WatchItem.sort_order.asc(), WatchItem.id.asc())
        .all()
    )


def _codes_from_items(items: list[dict]) -> tuple[list[str], dict[str, str]]:
    codes = [x.get("code_full") or x.get("code6") or x.get("code") for x in items]
    names = {x.get("code6") or x.get("code"): x.get("name", "") for x in items}
    return codes, names


@router.get("/watchlist")
def get_watchlist(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [_watch_payload(i) for i in _watch_ordered(db, user)]


@router.put("/watchlist")
def put_watchlist(body: WatchIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    previous = {i.code6: card_dict(i) | {"group": i.group_name} for i in db.query(WatchItem).filter_by(user_id=user.id).all()}
    db.query(WatchItem).filter_by(user_id=user.id).delete()
    codes, names = _codes_from_items(body.items)
    insts = resolve_instruments(codes, market)
    saved = []
    for inst in insts:
        group = "自选"
        for raw in body.items:
            token = raw.get("code6") or raw.get("code") or ""
            if token == inst.code6 or raw.get("code_full") == inst.code_full:
                group = raw.get("group") or raw.get("group_name") or "自选"
                break
        old = previous.get(inst.code6) or {}
        if group not in GROUPS:
            group = old.get("group") or "自选"
        item = WatchItem(
            user_id=user.id,
            code6=inst.code6,
            code_full=inst.code_full,
            name=inst.name or names.get(inst.code6, ""),
            group_name=group if group in GROUPS else "自选",
            thesis=old.get("thesis") or "",
            cost=old.get("cost"),
            shares=old.get("shares"),
            buy_low=old.get("buy_low"),
            buy_high=old.get("buy_high"),
            reduce_price=old.get("reduce_price"),
            invalid_if=old.get("invalid_if") or "",
            sort_order=len(saved),
        )
        db.add(item)
        saved.append(_watch_payload(item))
    db.commit()
    _sync_clock_universe(user, db)
    bus.publish("universe.changed", {"user_id": user.id, "count": len(saved)}, "platform")
    return saved


@router.post("/watchlist/items")
def add_watch_items(body: WatchIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    codes, names = _codes_from_items(body.items)
    insts = resolve_instruments(codes, market)
    existing_rows = _watch_ordered(db, user)
    existing = {i.code6: i for i in existing_rows}
    nxt = (existing_rows[-1].sort_order + 1) if existing_rows else 0
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
            sort_order=nxt,
        )
        nxt += 1
        db.add(item)
        existing[inst.code6] = item
        added.append(_watch_payload(item))
    db.commit()
    items = [_watch_payload(i) for i in _watch_ordered(db, user)]
    _sync_clock_universe(user, db)
    bus.publish("universe.changed", {"user_id": user.id, "count": len(items)}, "platform")
    return {"added": added, "items": items}


@router.delete("/watchlist/{code6}")
def delete_watch_item(code6: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.query(WatchItem).filter_by(user_id=user.id, code6=code6).first()
    if not item:
        raise HTTPException(status_code=404, detail="自选中没有这只股票")
    db.delete(item)
    db.commit()
    remain = _watch_ordered(db, user)
    _sync_clock_universe(user, db)
    bus.publish("universe.changed", {"user_id": user.id, "count": len(remain)}, "platform")
    return {"removed": code6, "items": [_watch_payload(i) for i in remain]}


@router.put("/watchlist/order")
def put_watch_order(body: WatchOrderIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = {i.code6: i for i in db.query(WatchItem).filter_by(user_id=user.id).all()}
    if not items:
        return []
    ordered: list[WatchItem] = []
    seen: set[str] = set()
    for raw in body.codes or []:
        code = str(raw or "").split(".")[0].strip()
        row = items.get(code)
        if row is None or code in seen:
            continue
        ordered.append(row)
        seen.add(code)
    for row in _watch_ordered(db, user):
        if row.code6 not in seen:
            ordered.append(row)
    for idx, row in enumerate(ordered):
        row.sort_order = idx
    db.commit()
    return [_watch_payload(i) for i in _watch_ordered(db, user)]


@router.put("/watchlist/{code6}/card")
def put_watch_card(code6: str, body: CardIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    item = db.query(WatchItem).filter_by(user_id=user.id, code6=code6).first()
    if not item:
        raise HTTPException(status_code=404, detail="自选中没有这只股票")
    if body.group and body.group not in GROUPS:
        raise HTTPException(status_code=400, detail="分组只支持 自选 / 观察 / 备选")
    item.thesis = (body.thesis or "")[:2000]
    item.cost = body.cost
    item.shares = body.shares
    item.buy_low = body.buy_low
    item.buy_high = body.buy_high
    item.reduce_price = body.reduce_price
    item.invalid_if = (body.invalid_if or "")[:500]
    if body.group:
        item.group_name = body.group
    db.commit()
    db.refresh(item)
    return _watch_payload(item)


@router.get("/markets/instruments")
def instruments(q: str = "", board: str = Query("all", alias="market"), limit: int = 50):
    return market.search(q, board, max(1, min(limit, 200)))


@router.get("/markets/board")
def market_board():
    return {"items": market.index_quotes(), "market": market.health()}


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
    return insts, fields, name, meta, _cards_map(db, user)


def _execute_query(insts, fields: list[str], do_export: bool, pool_name: str, user_id: int, cards: dict | None = None, writer: str = "") -> dict:
    rows = engine.run(insts, fields, cards=cards, writer=writer)
    codes = [i.code_full for i in insts]
    out = {
        "fields": _field_view(fields),
        "rows": rows,
        "pool": pool_name,
        "count": len(rows),
        "market": market.health(),
        "clock": {
            "as_of": (rows[0].get("as_of") if rows else "") or "",
            "source": (rows[0].get("quote_source") if rows else "") or "",
        },
    }
    if do_export:
        path = write_query_xlsx(rows, fields, pool_name)
        db = SessionLocal()
        try:
            rec = record_artifact(
                db,
                user_id=user_id,
                path=path,
                pool_name=pool_name,
                field_keys=fields,
                codes=codes,
            )
            out["id"] = rec.id
            out["filename"] = rec.filename
            out["path"] = rec.path
            out["download_url"] = f"/api/artifacts/{rec.id}/download"
        finally:
            db.close()
    return out


def _run_or_enqueue(body: QueryIn, user: User, db: Session, do_export: bool):
    insts, fields, pool_name, meta, cards = _prepare_query(body, user, db)
    use_job = body.async_mode or len(insts) > settings.query_sync_limit
    if not use_job:
        result = _execute_query(insts, fields, do_export, pool_name, user.id, cards, writer=user.username)
        result["sample"] = meta.get("sample", False)
        result["note"] = meta.get("note") or ""
        result["pool_id"] = meta.get("id")
        return result
    job = jobs.create("export" if do_export else "query", meta.get("id") or body.pool, len(insts))
    snapshot = list(insts)

    def worker():
        try:
            result = _execute_query(snapshot, fields, do_export, pool_name, user.id, cards, writer=user.username)
            result["sample"] = meta.get("sample", False)
            result["note"] = meta.get("note") or ""
            result["pool_id"] = meta.get("id")
            jobs.finish(job.id, result)
        except Exception as exc:
            jobs.fail(job.id, str(exc))

    jobs.spawn(worker)
    return bg_job_payload(job)


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
    return bg_job_payload(job)


@router.post("/artifacts/diff")
def artifacts_diff(body: DiffIn | None = None, user: User = Depends(current_user), db: Session = Depends(get_db)):
    args: dict = {}
    if body:
        if body.id_a:
            args["id_a"] = body.id_a
        if body.id_b:
            args["id_b"] = body.id_b
        if body.column:
            args["column"] = body.column
    return _tool_http(excel_diff(args, _tool_ctx(user, db)))


@router.get("/artifacts/{art_id}/preview")
def preview_artifact(art_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return _tool_http(excel_read({"id": art_id, "limit": 30}, _tool_ctx(user, db)))


@router.get("/warehouse")
def warehouse(
    kind: str = "list",
    code: str = "",
    key: str = "",
    id: int | None = None,
    limit: int = 40,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    args: dict = {"kind": kind, "limit": limit}
    if code:
        args["code"] = code
    if key:
        args["key"] = key
    if id:
        args["id"] = id
    return _tool_http(warehouse_get(args, _tool_ctx(user, db)))


@router.get("/storage")
def get_storage(user: User = Depends(current_user), db: Session = Depends(get_db)):
    snap = usage()
    count = db.query(Artifact).filter_by(user_id=user.id).count()
    snap["artifact_records"] = count
    snap["clock"] = clock_status()
    return snap


@router.post("/storage/cache/clear")
def storage_clear_cache(user: User = Depends(current_user)):
    return clear_cache()


@router.post("/storage/artifacts/prune")
def storage_prune_artifacts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    result = prune_artifacts(db, user_id=user.id)
    result["usage"] = usage()
    result["artifact_records"] = db.query(Artifact).filter_by(user_id=user.id).count()
    return result


@router.post("/storage/enforce")
def storage_enforce(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return enforce_all(db, user_id=user.id)


@router.get("/clock")
def get_clock(user: User = Depends(current_user)):
    return clock_status()


@router.post("/clock/dir")
def post_clock_dir(body: ClockDirIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    raw = (body.path or "").strip().strip('"')
    if not raw:
        raise HTTPException(status_code=400, detail="请填写账本文件夹路径")
    try:
        set_clock_dir(Path(raw))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _sync_clock_universe(user, db)
    return clock_status()


@router.get("/clock/slots")
def get_clock_slots(date: str = "", user: User = Depends(current_user)):
    root = configured_clock_dir()
    if root is None:
        return {"enabled": False, "slots": []}
    return {"enabled": True, "slots": list_slots(root, date or None)}


@router.get("/clock/slot")
def get_clock_slot(as_of: str, user: User = Depends(current_user)):
    root = configured_clock_dir()
    if root is None:
        raise HTTPException(status_code=400, detail="未选择账本文件夹")
    payload = load_slot(root, as_of)
    if not payload:
        return {"as_of": as_of, "quotes": {}, "codes": [], "missing": True}
    return {**payload, "missing": False}


@router.get("/clock/series")
def get_clock_series(code: str, start: str, end: str, user: User = Depends(current_user)):
    root = configured_clock_dir()
    if root is None:
        return {"enabled": False, "points": [], "code": (code or "").split(".")[0]}
    code6 = (code or "").split(".")[0]
    return {"enabled": True, "code": code6, "points": clock_series(root, code6, start, end)}


@router.get("/export-share")
def get_export_share(code: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    args: dict = {}
    if code:
        args["code"] = code
    return _tool_http(export_share(args, _tool_ctx(user, db)))


@router.put("/export-share")
async def put_export_share(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
):
    name = (file.filename or "").lower()
    if not name.endswith(".csv"):
        raise HTTPException(status_code=400, detail="只接受 .csv")
    raw = await file.read()
    if len(raw) > 2_000_000:
        raise HTTPException(status_code=400, detail="文件超过 2MB")
    path = settings.data_dir / "export_share.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return {"ok": True, "filename": path.name, "bytes": len(raw)}


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
    loaded = load_manifests()
    names = reload_policies()
    return {"loaded": loaded, "policies": names}


@router.get("/agent/policy")
def agent_policy():
    return policies_public()


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
    return [job_payload(j) for j in jobs_list]


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
    return job_payload(job)


@router.put("/monitor/jobs/{job_key}")
def patch_job(job_key: str, body: JobPatchIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_jobs(db, user)
    job = db.query(MonitorJob).filter_by(user_id=user.id, job_key=job_key).first()
    if not job:
        raise HTTPException(status_code=404, detail="没有这个监控项")
    if body.enabled is not None:
        if job.reason and body.enabled:
            raise HTTPException(status_code=409, detail=job.reason)
        job.enabled = 1 if body.enabled else 0
    if body.params is not None:
        current = json.loads(job.params or "{}") if job.params else {}
        if not isinstance(current, dict):
            current = {}
        current.update(body.params)
        if "definition" in current:
            current["definition"] = clip_note(current.get("definition"))
        if "need" in current:
            current["need"] = clip_note(current.get("need"))
        job.params = json.dumps(current, ensure_ascii=False)
    if body.schedule:
        if body.schedule not in {"session", "eod"}:
            raise HTTPException(status_code=400, detail="扫描时点只支持盘中或日终")
        job.schedule = body.schedule
    db.commit()
    db.refresh(job)
    return job_payload(job)


@router.post("/monitor/jobs/{job_key}/run")
def run_one_job(job_key: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    ensure_jobs(db, user)
    return run_watcher(db, user, market, job_key)


@router.post("/monitor/run")
def run_all_jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return run_watcher(db, user, market)


@router.get("/monitor/metrics")
def monitor_metrics():
    return metric_specs()


@router.get("/monitor/queue")
def monitor_queue(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return today_queue(db, user.id)


@router.get("/monitor/rules")
def list_rules(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.query(UserRule).filter_by(user_id=user.id).order_by(UserRule.id.desc()).all()
    return [rule_payload(r) for r in rows]


@router.post("/monitor/rules")
def create_rule(body: RuleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        spec = validate_custom_spec({**body.spec, "name": body.name or body.spec.get("name")})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row = UserRule(
        user_id=user.id,
        name=spec["name"],
        enabled=1 if body.enabled else 0,
        spec=json.dumps(spec, ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return rule_payload(row)


@router.put("/monitor/rules/{rule_id}")
def update_rule(rule_id: int, body: RuleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.query(UserRule).filter_by(id=rule_id, user_id=user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="没有这条规则")
    try:
        spec = validate_custom_spec({**body.spec, "name": body.name or body.spec.get("name") or row.name})
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    row.name = spec["name"]
    row.enabled = 1 if body.enabled else 0
    row.spec = json.dumps(spec, ensure_ascii=False)
    db.commit()
    db.refresh(row)
    return rule_payload(row)


@router.delete("/monitor/rules/{rule_id}")
def delete_rule(rule_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.query(UserRule).filter_by(id=rule_id, user_id=user.id).first()
    if not row:
        raise HTTPException(status_code=404, detail="没有这条规则")
    db.delete(row)
    db.commit()
    return {"removed": rule_id}


@router.post("/monitor/rules/preview")
def preview_rule(body: PreviewIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if body.job_key:
        return run_watcher(db, user, market, body.job_key, persist=False)
    if not body.spec:
        raise HTTPException(status_code=400, detail="请提供规则或选择一条模板")
    try:
        spec = validate_custom_spec(body.spec)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return run_watcher(db, user, market, persist=False, preview_spec=spec)


@router.get("/monitor/prefs")
def get_monitor_prefs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    pref = db.query(MonitorPref).filter_by(user_id=user.id).first()
    return pref_payload(pref)


@router.put("/monitor/prefs")
def put_monitor_prefs(body: MonitorPrefIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    payload = json.dumps({"selected": body.selected, "custom": body.custom}, ensure_ascii=False)
    pref = db.query(MonitorPref).filter_by(user_id=user.id).first()
    if pref:
        pref.institutions = payload
    else:
        pref = MonitorPref(user_id=user.id, institutions=payload)
        db.add(pref)
    db.commit()
    return pref_payload(pref)


@router.get("/alerts")
def list_alerts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    items = db.query(Alert).filter_by(user_id=user.id).order_by(Alert.id.desc()).limit(50).all()
    return [_alert_payload(i) for i in items]


@router.get("/monitor/reviews")
def list_reviews(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return reviews_payload(db, user.id)


@router.post("/monitor/review/run")
def run_reviews(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return run_reviewer(db, user, market)


@router.patch("/alerts/{alert_id}")
def patch_alert(alert_id: int, body: AlertPatchIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    rec = db.query(Alert).filter_by(id=alert_id, user_id=user.id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="没有这条提醒")
    if body.status not in {"open", "seen", "watch", "keep", "void"}:
        raise HTTPException(status_code=400, detail="处理动作无效")
    rec.status = body.status
    db.commit()
    return _alert_payload(rec)


def _alert_payload(i: Alert) -> dict:
    return {
        "id": i.id,
        "job_key": i.job_key,
        "rule_id": i.rule_id or i.job_key,
        "code6": i.code6,
        "title": i.title,
        "detail": i.detail,
        "status": i.status or "open",
        "severity": i.severity or "watch",
        "created_at": i.created_at.isoformat() if i.created_at else None,
        "hit_price": i.hit_price,
        "hit_date": i.hit_date or "",
        "review_status": i.review_status or "pending",
        "review_label": REVIEW_LABELS.get(i.review_status or "pending", i.review_status or "pending"),
        "review_return_pct": i.review_return_pct,
        "review_close": i.review_close,
        "reviewed_at": i.reviewed_at.isoformat() if i.reviewed_at else None,
        "review_note": i.review_note or "",
    }
