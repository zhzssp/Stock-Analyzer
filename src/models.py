from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(256))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class WatchItem(Base):
    __tablename__ = "watchlist"
    __table_args__ = (UniqueConstraint("user_id", "code_full"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    code6: Mapped[str] = mapped_column(String(16))
    code_full: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64), default="")
    group_name: Mapped[str] = mapped_column(String(32), default="自选")
    thesis: Mapped[str] = mapped_column(Text, default="")
    cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    shares: Mapped[float | None] = mapped_column(Float, nullable=True)
    buy_low: Mapped[float | None] = mapped_column(Float, nullable=True)
    buy_high: Mapped[float | None] = mapped_column(Float, nullable=True)
    reduce_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    invalid_if: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    path: Mapped[str] = mapped_column(String(512))
    filename: Mapped[str] = mapped_column(String(256))
    pool_name: Mapped[str] = mapped_column(String(64), default="自选")
    field_keys: Mapped[str] = mapped_column(Text, default="[]")
    codes: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class FieldPref(Base):
    __tablename__ = "field_prefs"
    __table_args__ = (UniqueConstraint("user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    field_keys: Mapped[str] = mapped_column(Text, default="[]")
    preset: Mapped[str] = mapped_column(String(16), default="watch")


class ConceptPref(Base):
    __tablename__ = "concept_prefs"
    __table_args__ = (UniqueConstraint("user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    payload: Mapped[str] = mapped_column(Text, default="[]")


class Snapshot(Base):
    __tablename__ = "snapshots"
    __table_args__ = (UniqueConstraint("user_id", "code6", "kind"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    code6: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class MonitorJob(Base):
    __tablename__ = "monitor_jobs"
    __table_args__ = (UniqueConstraint("user_id", "job_key"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    job_key: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(64))
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    reason: Mapped[str] = mapped_column(String(128), default="")
    params: Mapped[str] = mapped_column(Text, default="{}")
    kind: Mapped[str] = mapped_column(String(16), default="template")
    schedule: Mapped[str] = mapped_column(String(16), default="eod")
    severity: Mapped[str] = mapped_column(String(16), default="watch")


class MonitorPref(Base):
    __tablename__ = "monitor_prefs"
    __table_args__ = (UniqueConstraint("user_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    institutions: Mapped[str] = mapped_column(Text, default="")


class UserRule(Base):
    __tablename__ = "user_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(64), default="")
    enabled: Mapped[int] = mapped_column(Integer, default=1)
    spec: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AgentSession(Base):
    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    title: Mapped[str] = mapped_column(String(128), default="")
    agent: Mapped[str] = mapped_column(String(32), default="analyst")
    messages: Mapped[str] = mapped_column(Text, default="[]")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    job_key: Mapped[str] = mapped_column(String(32))
    code6: Mapped[str] = mapped_column(String(16), default="")
    title: Mapped[str] = mapped_column(String(128))
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    status: Mapped[str] = mapped_column(String(16), default="open")
    severity: Mapped[str] = mapped_column(String(16), default="watch")
    rule_id: Mapped[str] = mapped_column(String(64), default="")
    hit_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    hit_date: Mapped[str] = mapped_column(String(16), default="")
    review_status: Mapped[str] = mapped_column(String(16), default="pending")
    review_return_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    review_close: Mapped[float | None] = mapped_column(Float, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    review_note: Mapped[str] = mapped_column(Text, default="")
