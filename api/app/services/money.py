"""Money helpers — float storage with Decimal-safe 2dp rounding."""

from decimal import Decimal, ROUND_HALF_UP


def round_money(value: float | int | str | Decimal) -> float:
    """Round to 2 decimal places (half up) to limit float drift on writes."""
    d = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(d)
