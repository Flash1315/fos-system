"""Lightweight additive schema upgrades for SQLite/Postgres (pre-Alembic safety net)."""

import logging

from sqlalchemy import text

from app.db import engine

logger = logging.getLogger(__name__)


def _ensure_columns(table: str, ddl: list[tuple[str, str]]) -> None:
    with engine.begin() as conn:
        dialect = engine.dialect.name
        if dialect == "sqlite":
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            existing = {r[1] for r in rows}
            for name, typ in ddl:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {typ}"))
                    logger.info("schema: added %s.%s", table, name)
        else:
            for name, typ in ddl:
                exists = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name=:t AND column_name=:c"
                    ),
                    {"t": table, "c": name},
                ).fetchone()
                if not exists:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {typ}"))
                    logger.info("schema: added %s.%s", table, name)


def ensure_money_record_columns() -> None:
    """Add new columns if missing (no full Alembic dependency on boot)."""
    _ensure_columns(
        "money_records",
        [
            ("purpose", "VARCHAR(80) DEFAULT ''"),
            ("place", "VARCHAR(200) DEFAULT ''"),
            ("payment_source", "VARCHAR(40) DEFAULT ''"),
            ("bike", "VARCHAR(120) DEFAULT ''"),
            ("occurred_at", "DATETIME"),
            ("is_voided", "BOOLEAN DEFAULT 0"),
            ("voided_at", "DATETIME"),
            ("voided_by", "INTEGER"),
            ("transfer_group_id", "VARCHAR(40)"),
        ],
    )
    _ensure_columns(
        "payouts",
        [
            ("overpayment", "FLOAT DEFAULT 0"),
            ("balance_after", "FLOAT DEFAULT 0"),
            ("is_voided", "BOOLEAN DEFAULT 0"),
            ("voided_at", "DATETIME"),
            ("voided_by", "INTEGER"),
            ("void_note", "TEXT DEFAULT ''"),
        ],
    )
    _ensure_columns(
        "settlement_requests",
        [
            ("settled_amount", "FLOAT"),
            ("payout_id", "INTEGER"),
        ],
    )
    _ensure_columns(
        "users",
        [
            ("token_version", "INTEGER DEFAULT 0"),
            ("invite_token", "VARCHAR(64)"),
            ("invite_token_expires_at", "DATETIME"),
            ("must_set_password", "BOOLEAN DEFAULT 0"),
        ],
    )
    _ensure_columns(
        "organizations",
        [
            ("plan", "VARCHAR(40) DEFAULT 'free'"),
            ("billing_status", "VARCHAR(40) DEFAULT 'ok'"),
            ("telegram_chat_id", "VARCHAR(64) DEFAULT ''"),
        ],
    )
    _ensure_columns(
        "idempotency_keys",
        [
            ("response_json", "TEXT"),
        ],
    )
