from sqlalchemy.orm import Session

from src.config import settings
from src.market.fixtures import CARD_SEED, WATCH_SEED
from src.agents.watcher import ensure_jobs
from src.models import User, WatchItem
from src.platform.security import hash_password


def _card_empty(item: WatchItem) -> bool:
    return not (
        (item.thesis or "").strip()
        or item.cost is not None
        or item.shares is not None
        or item.buy_low is not None
        or item.buy_high is not None
        or item.reduce_price is not None
        or (item.invalid_if or "").strip()
    )


def _apply_card_seed(item: WatchItem, seed: dict) -> None:
    item.group_name = seed.get("group") or item.group_name or "自选"
    item.thesis = seed.get("thesis") or ""
    item.cost = seed.get("cost")
    item.shares = seed.get("shares")
    item.buy_low = seed.get("buy_low")
    item.buy_high = seed.get("buy_high")
    item.reduce_price = seed.get("reduce_price")
    item.invalid_if = seed.get("invalid_if") or ""


def bootstrap(db: Session) -> None:
    user = db.query(User).filter_by(username=settings.bootstrap_user).first()
    if not user:
        user = User(
            username=settings.bootstrap_user,
            password_hash=hash_password(settings.bootstrap_password),
        )
        db.add(user)
        db.flush()
    existing = {w.code6: w for w in db.query(WatchItem).filter_by(user_id=user.id).all()}
    for inst in WATCH_SEED:
        item = existing.get(inst.code6)
        if item is None:
            item = WatchItem(
                user_id=user.id,
                code6=inst.code6,
                code_full=inst.code_full,
                name=inst.name,
                group_name="自选",
            )
            db.add(item)
            db.flush()
            existing[inst.code6] = item
        seed = CARD_SEED.get(inst.code6)
        if seed and _card_empty(item):
            _apply_card_seed(item, seed)
    db.commit()
    ensure_jobs(db, user)
