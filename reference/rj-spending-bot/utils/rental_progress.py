import json
import os

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rental_progress.json")


def _load_all() -> dict:
    if not os.path.exists(PROGRESS_FILE):
        return {}
    try:
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"rental_progress load error: {e}")
        return {}


def _save_all(data: dict) -> None:
    try:
        with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"rental_progress save error: {e}")


def save_progress(user_id: int, flow: str, state_key: str, data: dict) -> None:
    all_data = _load_all()
    all_data[str(user_id)] = {
        "flow": flow,
        "state": state_key,
        "data": data,
    }
    _save_all(all_data)


def load_progress(user_id: int) -> dict:
    return _load_all().get(str(user_id)) or {}


def clear_progress(user_id: int) -> None:
    all_data = _load_all()
    if str(user_id) in all_data:
        del all_data[str(user_id)]
        _save_all(all_data)


def get_resume_label(user_id: int) -> str:
    p = load_progress(user_id)
    if not p:
        return ""
    if p.get("flow") == "delivery":
        return "▶ Resume delivery"
    if p.get("flow") == "return":
        return "▶ Resume return"
    return ""
