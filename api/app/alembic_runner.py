"""Optional runtime Alembic upgrade (safe no-op if already at head)."""

from pathlib import Path


def run_alembic_upgrade() -> None:
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:
        print("schema: alembic not installed — skipping upgrade")
        return
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    try:
        command.upgrade(cfg, "head")
        print("schema: alembic upgrade head ok")
    except Exception as exc:  # noqa: BLE001
        print(f"schema: alembic upgrade skipped/failed: {exc}")
