"""Optional runtime Alembic upgrade (safe no-op if already at head)."""

import logging
from pathlib import Path

from app.config import settings

logger = logging.getLogger(__name__)


def run_alembic_upgrade() -> None:
    env = (settings.environment or "development").strip().lower()
    is_prod = env in ("prod", "production")
    try:
        from alembic import command
        from alembic.config import Config
    except ImportError:
        msg = "schema: alembic not installed — skipping upgrade"
        if is_prod:
            raise RuntimeError("Alembic is required in production") from None
        logger.info(msg)
        return
    root = Path(__file__).resolve().parents[1]
    cfg = Config(str(root / "alembic.ini"))
    cfg.set_main_option("script_location", str(root / "alembic"))
    try:
        command.upgrade(cfg, "head")
        logger.info("schema: alembic upgrade head ok")
    except Exception as exc:  # noqa: BLE001
        if is_prod:
            raise RuntimeError(f"Alembic upgrade failed in production: {exc}") from exc
        logger.warning("schema: alembic upgrade skipped/failed: %s", exc)
