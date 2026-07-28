"""hot query indexes

Revision ID: 20260728_0002
Revises: 20260728_0001
Create Date: 2026-07-28

"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260728_0002"
down_revision: Union[str, None] = "20260728_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_INDEXES = [
    ("ix_users_org_active", "users", ["organization_id", "is_active"]),
    (
        "ix_money_records_org_creator_created",
        "money_records",
        ["organization_id", "created_by", "created_at"],
    ),
    (
        "ix_money_records_org_status_void_created",
        "money_records",
        ["organization_id", "status", "is_voided", "created_at"],
    ),
    (
        "ix_money_records_org_creator_status_void",
        "money_records",
        ["organization_id", "created_by", "status", "is_voided"],
    ),
    ("ix_money_records_transfer_group", "money_records", ["transfer_group_id"]),
    (
        "ix_payouts_org_user_kind_void_created",
        "payouts",
        ["organization_id", "user_id", "kind", "is_voided", "created_at"],
    ),
    (
        "ix_settlement_requests_org_status_created",
        "settlement_requests",
        ["organization_id", "status", "created_at"],
    ),
    (
        "ix_settlement_requests_org_user_status",
        "settlement_requests",
        ["organization_id", "user_id", "status"],
    ),
    ("ix_idempotency_keys_created_at", "idempotency_keys", ["created_at"]),
]


def upgrade() -> None:
    for name, table, cols in _INDEXES:
        op.create_index(name, table, cols, if_not_exists=True)


def downgrade() -> None:
    for name, table, _cols in reversed(_INDEXES):
        op.drop_index(name, table_name=table, if_exists=True)
