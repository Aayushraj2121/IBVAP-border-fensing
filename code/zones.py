"""
IBVAP - zones.py: Zone Storage & Persistence Manager
Supports single-camera web editor (rule.py / webapi.py) and multi-stream zones.
"""
import os
import json

ZONES_PATH = "data/zones.json"


def file_mtime(path: str = ZONES_PATH) -> float:
    """Returns modification timestamp of zones file."""
    return os.path.getmtime(path) if os.path.exists(path) else 0.0


def load_zones(path: str = ZONES_PATH) -> list:
    """Loads zone list from JSON file with backward/forward compatibility."""
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                # Flatten any list values if stored as stream-keyed dictionary
                all_zones = []
                for k, v in data.items():
                    if isinstance(v, list):
                        all_zones.extend(v)
                return all_zones
    except Exception as e:
        print(f"⚠️ Failed to load zones from {path}: {e}")
    return []


def save_zones(zones: list, path: str = ZONES_PATH):
    """Saves zones list to JSON file."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(zones, f, indent=2)
