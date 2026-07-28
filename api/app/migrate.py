"""Lightweight additive schema upgrades for SQLite/Postgres."""

from sqlalchemy import text

from app.db import engine


def _ensure_columns(table: str, ddl: list[tuple[str, str]]) -> None:
    with engine.begin() as conn:
        dialect = engine.dialect.name
        if dialect == "sqlite":
            rows = conn.execute(text(f"PRAGMA table_info({table})")).fetchall()
            existing = {r[1] for r in rows}
            for name, typ in ddl:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {typ}"))
                    print(f"schema: added {table}.{name}")
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
                    print(f"schema: added {table}.{name}")


def ensure_money_record_columns() -> None:
    """Add new MoneyRecord / Payout columns if missing (no Alembic in v1)."""
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
