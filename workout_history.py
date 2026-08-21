"""Persistente Workout-Historie – gespeichert neben der Anwendung."""
import json
import logging
from datetime import datetime
from pathlib import Path

from app_paths import app_dir

_MAX_ENTRIES = 200
LOGGER = logging.getLogger(__name__)


def _history_file() -> Path:
    return app_dir() / "workout_history.json"


def load_history() -> list:
    """Lädt alle gespeicherten Einträge. Gibt bei Fehler leere Liste zurück."""
    try:
        history_file = _history_file()
        if history_file.exists():
            with open(history_file, encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
    except Exception as exc:
        LOGGER.warning("Could not load workout history: %s", exc)
    return []


def save_entry(entry: dict) -> None:
    """Hängt einen Eintrag an; begrenzt auf _MAX_ENTRIES neueste Einträge."""
    history = load_history()
    history.append(entry)
    if len(history) > _MAX_ENTRIES:
        history = history[-_MAX_ENTRIES:]
    try:
        history_file = _history_file()
        history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
    except Exception as exc:
        LOGGER.warning("Could not save workout history: %s", exc)


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
