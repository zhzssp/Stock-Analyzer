from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine

from src.db import Base

_COLUMNS = {
    "watchlist": [
        ("thesis", "TEXT DEFAULT ''"),
        ("cost", "FLOAT"),
        ("shares", "FLOAT"),
        ("buy_low", "FLOAT"),
        ("buy_high", "FLOAT"),
        ("reduce_price", "FLOAT"),
        ("invalid_if", "TEXT DEFAULT ''"),
    ],
    "monitor_jobs": [
        ("params", "TEXT DEFAULT '{}'"),
        ("kind", "VARCHAR(16) DEFAULT 'template'"),
        ("schedule", "VARCHAR(16) DEFAULT ''"),
        ("severity", "VARCHAR(16) DEFAULT ''"),
    ],
    "alerts": [
        ("status", "VARCHAR(16) DEFAULT 'open'"),
        ("severity", "VARCHAR(16) DEFAULT 'watch'"),
        ("rule_id", "VARCHAR(64) DEFAULT ''"),
        ("hit_price", "FLOAT"),
        ("hit_date", "VARCHAR(16) DEFAULT ''"),
        ("review_status", "VARCHAR(16) DEFAULT 'pending'"),
        ("review_return_pct", "FLOAT"),
        ("review_close", "FLOAT"),
        ("reviewed_at", "DATETIME"),
        ("review_note", "TEXT DEFAULT ''"),
    ],
}


def _existing(conn, table: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
    return {str(r[1]) for r in rows}


def migrate_schema(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    with engine.begin() as conn:
        tables = {str(r[0]) for r in conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()}
        for table, cols in _COLUMNS.items():
            if table not in tables:
                continue
            have = _existing(conn, table)
            for name, ddl in cols:
                if name in have:
                    continue
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
