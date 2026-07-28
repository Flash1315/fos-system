"""baseline — create current metadata (idempotent)

Revision ID: 20260728_0001
Revises:
Create Date: 2026-07-28

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260728_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    from app.db import Base
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=bind)


def downgrade() -> None:
    # Keep data — full drop is unsafe for multi-tenant production DBs
    pass
