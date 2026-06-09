"""Persistente Workout-Historie – gespeichert in %APPDATA%/treadmill-tray."""
import json
from datetime import datetime
from pathlib import Path

_HISTORY_DIR = Path.home() / "AppData" / "Roaming" / "treadmill-tray"
_HISTORY_FILE = _HISTORY_DIR / "workout_history.json"
_MAX_ENTRIES = 200


def load_history() -> list:
    """Lädt alle gespeicherten Einträge. Gibt bei Fehler leere Liste zurück."""
    try:
        if _HISTORY_FILE.exists():
            with open(_HISTORY_FILE, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def save_entry(entry: dict) -> None:
    """Hängt einen Eintrag an; begrenzt auf _MAX_ENTRIES neueste Einträge."""
    history = load_history()
    history.append(entry)
    if len(history) > _MAX_ENTRIES:
        history = history[-_MAX_ENTRIES:]
    try:
        _HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        with open(_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


def make_entry(
    start_time: datetime,
    duration_s: int,
    distance_km: float,
    steps: int,
    calories: int,
    avg_speed_kmh: float,
    target_speed_kmh: float,
    unit_mode: int = 0,
) -> dict:
    return {
        "start_time": start_time.isoformat(),
        "duration_s": duration_s,
        "distance_km": round(distance_km, 3),
        "steps": steps,
        "calories": calories,
        "avg_speed_kmh": round(avg_speed_kmh, 1),
        "target_speed_kmh": round(target_speed_kmh, 1),
        "unit": "imperial" if unit_mode == 1 else "metric",
    }
