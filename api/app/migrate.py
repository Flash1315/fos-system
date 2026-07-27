"""Lightweight additive schema upgrades for SQLite/Postgres."""

from sqlalchemy import text

from app.db import engine


def ensure_money_record_columns() -> None:
    """Add new MoneyRecord columns if missing (no Alembic in v1)."""
    ddl = [
        ("purpose", "VARCHAR(80) DEFAULT ''"),
        ("place", "VARCHAR(200) DEFAULT ''"),
        ("payment_source", "VARCHAR(40) DEFAULT ''"),
    ]
    with engine.begin() as conn:
        dialect = engine.dialect.name
        if dialect == "sqlite":
            rows = conn.execute(text("PRAGMA table_info(money_records)")).fetchall()
            existing = {r[1] for r in rows}
            for name, typ in ddl:
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE money_records ADD COLUMN {name} {typ}"))
                    print(f"schema: added money_records.{name}")
        else:
            for name, typ in ddl:
                exists = conn.execute(
                    text(
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name='money_records' AND column_name=:c"
                    ),
                    {"c": name},
                ).fetchone()
                if not exists:
                    conn.execute(text(f"ALTER TABLE money_records ADD COLUMN {name} {typ}"))
                    print(f"schema: added money_records.{name}")
