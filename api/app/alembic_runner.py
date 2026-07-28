"""Optional runtime Alembic upgrade (safe no-op if already at head)."""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def run_alembic_upgrade() -> None:
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:
        logger.info("schema: alembic not installed — skipping upgrade")
        return
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    try:
        command.upgrade(cfg, "head")
        logger.info("schema: alembic upgrade head ok")
    except Exception as exc:  # noqa: BLE001
        logger.warning("schema: alembic upgrade skipped/failed: %s", exc)
