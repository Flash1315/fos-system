"""Preset categories for field money records (generic; not RJ-specific)."""

from app.models import RecordKind

PRESETS: dict[RecordKind, list[str]] = {
    RecordKind.expense: [
        "supplies",
        "tools",
        "food",
        "transport",
        "repair",
        "rent",
        "utilities",
        "other",
    ],
    RecordKind.fuel: [
        "petrol",
        "diesel",
        "other",
    ],
    RecordKind.income: [
        "service",
        "sale",
        "rental",
        "deposit",
        "other",
    ],
}


def categories_for(kind: RecordKind | None = None) -> dict[str, list[str]]:
    if kind is None:
        return {k.value: v for k, v in PRESETS.items()}
    return {kind.value: PRESETS[kind]}
