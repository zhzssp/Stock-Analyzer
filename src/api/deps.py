from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from src.db import get_db
from src.models import User
from src.platform.security import read_token


def current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="未登录")
    payload = read_token(authorization.split(" ", 1)[1])
    if not payload:
        raise HTTPException(status_code=401, detail="登录已过期")
    user = db.get(User, payload["uid"])
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    return user
