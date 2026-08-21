"""Speicherort der App-Dateien (config.json, workout_history.json).

Liegt bewusst neben der .exe (bzw. dem Skript im Dev-Betrieb) statt in
%APPDATA% -- die App ist als portables Tool gedacht: alles in einem Ordner.
"""
import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        # PyInstaller (--onefile): __file__ zeigt auf ein temporaeres
        # Extraktionsverzeichnis, das beim Beenden geloescht wird -- nicht
        # auf den tatsaechlichen Ort der .exe.
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent
