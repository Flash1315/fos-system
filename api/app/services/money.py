"""Money helpers — Decimal-safe 2dp rounding with float API surface."""

import math
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Union

MoneyLike = Union[float, int, str, Decimal]

# Matches Numeric(18, 2): 16 digits left of decimal + 2 right.
MAX_MONEY = Decimal("9999999999999999.99")


def as_decimal(value: MoneyLike) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Amount must be a finite number")
    try:
        raw = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("Amount must be a finite number") from exc
    if not raw.is_finite():
        raise ValueError("Amount must be a finite number")
    try:
        quantized = raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except InvalidOperation as exc:
        raise ValueError("Amount must be a finite number") from exc
    if abs(quantized) > MAX_MONEY:
        raise ValueError("Amount is too large")
    return quantized


def round_money(value: MoneyLike) -> float:
    """Round to 2 decimal places (half up) to limit float drift on writes."""
    amount = float(as_decimal(value))
    if not math.isfinite(amount):
        raise ValueError("Amount must be a finite number")
    return amount


def require_positive_money(value: MoneyLike) -> float:
    """Round then reject amounts that collapse to zero (e.g. 0.004 → 0.00)."""
    amount = round_money(value)
    if amount < 1e-9:
        raise ValueError("Amount must be at least 0.01 after rounding")
    return amount
