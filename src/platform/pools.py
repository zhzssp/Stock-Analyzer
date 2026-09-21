from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy.orm import Session

from src.market.client import MarketClient, resolve_instruments
from src.market.indices import all_index_pools, index_status
from src.market.normalize import Instrument
from src.models import User, WatchItem


EXCHANGE_POOLS = [
    {"id": "exchange:sh", "kind": "exchange", "label": "沪市全部", "enabled": True},
    {"id": "exchange:sz", "kind": "exchange", "label": "深市全部", "enabled": True},
    {"id": "exchange:bj", "kind": "exchange", "label": "北交所全部", "enabled": True},
]
BOARD_POOLS = [
    {"id": "board:cy", "kind": "board", "label": "创业板全部", "enabled": True},
    {"id": "board:kc", "kind": "board", "label": "科创板全部", "enabled": True},
]


def catalog() -> list[dict]:
    return [
        {"id": "watch", "kind": "watch", "label": "自选", "enabled": True},
        *EXCHANGE_POOLS,
        *BOARD_POOLS,
        *all_index_pools(),
    ]


def pool_label(pool_id: str) -> str:
    for item in catalog():
        if item["id"] == pool_id:
            return item["label"]
    return pool_id


def _payload(inst: Instrument) -> dict:
    return {
        "code6": inst.code6,
        "code_full": inst.code_full,
        "name": inst.name,
        "market": inst.market,
        "exchange": inst.exchange,
    }


def resolve_pool(
    pool_id: str,
    market: MarketClient,
    user: User | None = None,
    db: Session | None = None,
) -> tuple[list[Instrument], dict]:
    pid = (pool_id or "watch").strip() or "watch"
    meta = {"id": pid, "label": pool_label(pid), "sample": False, "note": ""}

    if market.sample_only and pid != "watch" and not pid.startswith("watch"):
        raise HTTPException(status_code=409, detail="演示 licence 忽略股票代码，不能把样本写成全市场或指数实盘")

    if pid == "watch":
        if user is None or db is None:
            raise HTTPException(status_code=400, detail="自选池需要登录")
        codes = [i.code_full for i in db.query(WatchItem).filter_by(user_id=user.id).order_by(WatchItem.sort_order.asc(), WatchItem.id.asc()).all()]
        insts = resolve_instruments(codes, market)
        meta["label"] = "自选"
        return insts, meta

    if pid.startswith("exchange:"):
        key = pid.split(":", 1)[1]
        insts = market.list_exchange(key)
        if market.offline:
            meta["sample"] = True
            meta["note"] = "离线切片，非全市场实盘"
        return insts, meta

    if pid.startswith("board:"):
        key = pid.split(":", 1)[1]
        insts = market.list_board(key)
        if market.offline:
            meta["sample"] = True
            meta["note"] = "离线切片，非全市场实盘"
        return insts, meta

    if pid.startswith("index:"):
        code = pid.split(":", 1)[1]
        insts = market.list_index(code)
        if not insts:
            st = index_status(code)
            reason = st["reason"] or "成份接口无数据"
            raise HTTPException(status_code=409, detail=f"{pool_label(pid)} 未启用：{reason}")
        meta["note"] = "指数成份股；不是该交易所全部挂牌"
        if market.offline:
            meta["sample"] = True
            meta["note"] = "离线成份切片，不是完整官方成份，也不是该交易所全部挂牌"
        return insts, meta

    raise HTTPException(status_code=400, detail=f"未知股票池: {pid}")
