"""Money helpers — Decimal-safe 2dp rounding with float API surface."""

from decimal import Decimal, ROUND_HALF_UP
from typing import Union

MoneyLike = Union[float, int, str, Decimal]


def as_decimal(value: MoneyLike) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_money(value: MoneyLike) -> float:
    """Round to 2 decimal places (half up) to limit float drift on writes."""
    return float(as_decimal(value))


def require_positive_money(value: MoneyLike) -> float:
    """Round then reject amounts that collapse to zero (e.g. 0.004 → 0.00)."""
    amount = round_money(value)
    if amount < 1e-9:
        raise ValueError("Amount must be at least 0.01 after rounding")
    return amount
