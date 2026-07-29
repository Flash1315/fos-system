"""Preset categories — multi-tenant presets inspired by RJ field ops (generic names)."""

from app.models import RecordKind

PURPOSES = ["Rental", "Lesson", "Office", "Other"]

PAYMENT_SOURCES = ["my_pocket", "cash_on_hand"]

PAYMENT_METHODS = ["cash", "transfer"]

PRESETS: dict[RecordKind, list[str]] = {
    RecordKind.expense: [
        "Bike service",
        "Aqua",
        "Training area renting",
        "Toll road top up",
        "Taxi",
        "Tires pressure / Wheel repair",
        "Supplies",
        "Food",
        "Transfer",
        "Other",
    ],
    RecordKind.fuel: [
        "Bensin",
        "Petrol",
        "Diesel",
        "Other",
    ],
    RecordKind.income: [
        "Rental",
        "Lesson",
        "Other (sales equipment etc.)",
        "Service",
        "Deposit",
        "Other",
    ],
}


def categories_for(kind: RecordKind | None = None) -> dict[str, list[str]]:
    if kind is None:
        return {k.value: v for k, v in PRESETS.items()}
    return {kind.value: PRESETS[kind]}
