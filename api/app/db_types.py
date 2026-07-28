"""SQLAlchemy money column — Numeric(18,2) storage, float API values."""

from decimal import Decimal

from sqlalchemy import Numeric
from sqlalchemy.types import TypeDecorator

from app.services.money import as_decimal


class MoneyAmount(TypeDecorator):
    """Bind Decimal to NUMERIC; expose float to existing routers/services."""

    impl = Numeric(18, 2)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return as_decimal(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, Decimal):
            return float(value)
        return float(value)
