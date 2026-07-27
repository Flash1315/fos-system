import json
import os

BIKES_CONFIG_FILE = "/root/rjbot/bikes_config.json"

def load_bikes():
    with open(BIKES_CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_bikes(config):
    with open(BIKES_CONFIG_FILE, 'w') as f:
        json.dump(config, f, indent=2)

def get_work_bikes():
    return load_bikes()["work"]

def get_rental_bikes():
    return load_bikes()["rental"]

def get_all_bikes():
    c = load_bikes()
    return c["work"] + c["rental"] + ["Other (enter manually)"]

def get_bike_category(bike_name: str) -> str:
    c = load_bikes()
    if bike_name in c["work"]:
        return "work"
    if bike_name in c["rental"]:
        return "rental"
    return "unknown"

def move_bike(bike_name, to_category):
    """Move bike between work/rental. to_category: 'work' or 'rental'"""
    c = load_bikes()
    from_category = "rental" if to_category == "work" else "work"
    if bike_name in c[from_category]:
        c[from_category].remove(bike_name)
        c[to_category].append(bike_name)
        save_bikes(c)
        return True
    return False
