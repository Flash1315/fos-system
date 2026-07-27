from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import MANAGERS
from keyboards.kb import rental_submenu_kb, back_cancel_kb
from utils.rental_rules import (
    FIELD_LABELS,
    add_field_rule,
    delete_field_rule,
    format_rules_list,
    load_rules,
    normalize_rule_phrase,
    normalize_rule_value,
)

router = Router()

TEACHABLE_FIELDS = [
    "location", "source", "bike_name", "delivery_time",
    "price", "duration_days", "helmets", "insurance",
    "delivery_date", "contact_info",
]

RULE_PHRASE_HINTS = {
    "price": "Short phrase only, e.g. <code>5 миллионов</code> or <code>5 million</code>",
    "location": "Short word from speech, e.g. <code>убуд</code>",
    "source": "Short phrase, e.g. <code>travel ask</code> or <code>ride joy</code>",
    "bike_name": "Short phrase, e.g. <code>nmax 5579</code>",
    "delivery_time": "e.g. <code>10:30</code> or <code>с 10.30 до 12.30</code>",
    "duration_days": "e.g. <code>2 месяца</code> or <code>60</code>",
}

RULE_VALUE_HINTS = {
    "price": "Number only: <code>5000000</code>",
    "location": "Location only: <code>Ubud</code>",
    "source": "<code>Ride&Joy</code> or <code>TravelAsk</code> only",
    "bike_name": "Exact bike name from list, e.g. <code>Nmax 5579</code>",
    "delivery_time": "e.g. <code>10:30-12:30</code>",
    "duration_days": "Days number, e.g. <code>60</code>",
    "helmets": "Number, e.g. <code>2</code>",
    "insurance": "<code>No insurance</code> or <code>With insurance</code>",
    "delivery_date": "Date, e.g. <code>28.05.2026</code>",
    "contact_info": "Contact only, e.g. <code>@username</code>",
}


class AiRulesState(StatesGroup):
    menu = State()
    pick_field = State()
    enter_phrase = State()
    enter_value = State()
    delete_pick = State()


def is_manager(uid: int) -> bool:
    return uid in MANAGERS


def rules_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Add rule", callback_data="airule:add")],
        [InlineKeyboardButton(text="🗑 Delete rule", callback_data="airule:del")],
        [InlineKeyboardButton(text="« Back", callback_data="airule:back")],
    ])


def field_pick_kb(prefix: str) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for field in TEACHABLE_FIELDS:
        label = FIELD_LABELS.get(field, field)
        row.append(InlineKeyboardButton(text=label, callback_data=f"{prefix}:{field}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="❌ Cancel", callback_data=f"{prefix}:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_rules_menu(message: Message, state: FSMContext):
    await state.set_state(AiRulesState.menu)
    await message.answer(
        format_rules_list()
        + "\n\n<i>One rule = one field.</i>\n"
        "Example: phrase <b>убуд</b> → Location = <b>Ubud</b>\n"
        "Example: phrase <b>5 миллионов</b> → Price = <b>5000000</b>",
        parse_mode="HTML",
        reply_markup=rules_menu_kb(),
    )


@router.message(F.text == "📚 Teach AI")
async def teach_ai_menu(message: Message, state: FSMContext):
    if not is_manager(message.from_user.id):
        return
    await show_rules_menu(message, state)


@router.callback_query(F.data == "airule:back")
async def rules_back(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.clear()
    await call.message.edit_text("« Back to Bike Rental menu.")
    await call.message.answer("🏍 <b>Bike Rental</b>", reply_markup=rental_submenu_kb(), parse_mode="HTML")


@router.callback_query(F.data == "airule:add", AiRulesState.menu)
async def rules_add_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    await state.set_state(AiRulesState.pick_field)
    await call.message.edit_text(
        "➕ <b>Add parsing rule</b>\n\nChoose ONE field:",
        parse_mode="HTML",
        reply_markup=field_pick_kb("airule_field"),
    )


@router.callback_query(F.data.startswith("airule_field:"), AiRulesState.pick_field)
async def rules_add_field(call: CallbackQuery, state: FSMContext):
    await call.answer()
    field = call.data.split(":", 1)[1]
    if field == "cancel":
        await show_rules_menu(call.message, state)
        return
    await state.update_data(rule_field=field)
    await state.set_state(AiRulesState.enter_phrase)
    label = FIELD_LABELS.get(field, field)
    hint = RULE_PHRASE_HINTS.get(field, "Short phrase from voice/text")
    await call.message.edit_text(
        f"➕ Field: <b>{label}</b>\n\n"
        f"Send trigger phrase.\n{hint}",
        parse_mode="HTML",
    )
    await call.message.answer("👇 Enter phrase:", reply_markup=back_cancel_kb())


@router.message(AiRulesState.enter_phrase)
async def rules_add_phrase(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Cancelled.", reply_markup=rental_submenu_kb())
        return
    if message.text == "⬅️ Back":
        await show_rules_menu(message, state)
        return
    data = await state.get_data()
    field = data.get("rule_field", "")
    phrase, err = normalize_rule_phrase(field, (message.text or "").strip())
    if err:
        await message.answer(f"⚠️ {err}")
        return
    await state.update_data(rule_phrase=phrase)
    label = FIELD_LABELS.get(field, field)
    hint = RULE_VALUE_HINTS.get(field, "Value for this field only")
    await state.set_state(AiRulesState.enter_value)
    await message.answer(
        f"Phrase: <i>{phrase}</i>\nField: <b>{label}</b>\n\n"
        f"Now send value for this field ONLY.\n{hint}",
        parse_mode="HTML",
        reply_markup=back_cancel_kb(),
    )


@router.message(AiRulesState.enter_value)
async def rules_add_value(message: Message, state: FSMContext):
    if message.text == "❌ Cancel":
        await state.clear()
        await message.answer("Cancelled.", reply_markup=rental_submenu_kb())
        return
    if message.text == "⬅️ Back":
        await state.set_state(AiRulesState.enter_phrase)
        await message.answer("Send phrase again:", reply_markup=back_cancel_kb())
        return
    value = (message.text or "").strip()
    data = await state.get_data()
    field = data.get("rule_field")
    phrase = data.get("rule_phrase")
    normalized, err = normalize_rule_value(field, value)
    if err:
        await message.answer(f"⚠️ {err}")
        return
    name = MANAGERS.get(message.from_user.id, {}).get("name", "")
    try:
        rule = add_field_rule(phrase, field, normalized, created_by=name)
    except ValueError as e:
        await message.answer(f"⚠️ {e}")
        return
    await state.clear()
    label = FIELD_LABELS.get(field, field)
    await message.answer(
        f"✅ Rule saved!\n\n"
        f"If message contains <i>{rule['contains']}</i>\n"
        f"→ {label} = <b>{rule['value']}</b>",
        parse_mode="HTML",
        reply_markup=rental_submenu_kb(),
    )


@router.callback_query(F.data == "airule:del", AiRulesState.menu)
async def rules_delete_start(call: CallbackQuery, state: FSMContext):
    await call.answer()
    rules = load_rules().get("field_rules", [])
    if not rules:
        await call.answer("No rules to delete.", show_alert=True)
        return
    buttons = []
    for r in rules:
        field = FIELD_LABELS.get(r.get("field", ""), r.get("field", ""))
        label = f"{r.get('contains', '')} → {field} = {r.get('value', '')}"
        if len(label) > 55:
            label = label[:52] + "..."
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"airule_rm:{r.get('id')}")])
    buttons.append([InlineKeyboardButton(text="❌ Cancel", callback_data="airule_rm:cancel")])
    await state.set_state(AiRulesState.delete_pick)
    await call.message.edit_text(
        "🗑 Tap rule to delete:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
    )


@router.callback_query(F.data.startswith("airule_rm:"), AiRulesState.delete_pick)
async def rules_delete_confirm(call: CallbackQuery, state: FSMContext):
    await call.answer()
    rule_id = call.data.split(":", 1)[1]
    if rule_id == "cancel":
        await show_rules_menu(call.message, state)
        return
    if delete_field_rule(rule_id):
        await call.message.edit_text("✅ Rule deleted.")
    else:
        await call.message.edit_text("❌ Rule not found.")
    await show_rules_menu(call.message, state)
