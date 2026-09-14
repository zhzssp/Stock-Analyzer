from sqlalchemy.orm import Session

from src.config import settings
from src.market.fixtures import WATCH_SEED
from src.models import User, WatchItem
from src.platform.security import hash_password


def bootstrap(db: Session) -> None:
    user = db.query(User).filter_by(username=settings.bootstrap_user).first()
    if not user:
        user = User(
            username=settings.bootstrap_user,
            password_hash=hash_password(settings.bootstrap_password),
        )
        db.add(user)
        db.flush()
    if db.query(WatchItem).filter_by(user_id=user.id).count() == 0:
        for inst in WATCH_SEED:
            db.add(
                WatchItem(
                    user_id=user.id,
                    code6=inst.code6,
                    code_full=inst.code_full,
                    name=inst.name,
                    group_name="自选",
                )
            )
    db.commit()
