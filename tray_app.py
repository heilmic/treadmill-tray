#!/usr/bin/env python3
"""
PitPat Treadmill – Windows System Tray App
Steuert das PitPat Laufband via Bluetooth direkt aus dem System-Tray.
"""

import asyncio
import json
import logging
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Optional
from pathlib import Path
from datetime import datetime


import pystray
from PIL import Image, ImageDraw
from bleak import BleakScanner

from bluetooth_manager_fba import BluetoothManagerFBA as BluetoothManager
from treadmill_controller import TreadmillController
from treadmill_data import TreadmillData
from workout_history import load_history, save_entry, make_entry

CONFIG_FILE = Path(__file__).parent / "config.json"
LOGGER = logging.getLogger(__name__)

# Kalibrierter Schätzwert: 50 gezählte Schritte wurden bei 0,75 m/Schritt nur
# als 34 gemeldet. Realistischere Schrittlänge laut Messung: ~0,51 m/Schritt.
_SCHRITT_LAENGE_M = 0.51


def _estimated_steps_from_distance(dist_m: int) -> int:
    return int(max(0, dist_m) / _SCHRITT_LAENGE_M)

# --- Farben (Dark Theme) ---
C_BG     = "#1a1b2e"
C_CARD   = "#16213e"
C_PANEL  = "#0f3460"
C_FG     = "#e0e0e0"
C_MUTED  = "#777"
C_ACCENT = "#4a9eff"
C_GREEN  = "#4CAF50"
C_YELLOW = "#FF9800"
C_RED    = "#f44336"

STATE_NAMES  = {0: "Startet", 1: "Läuft", 2: "Pausiert", 3: "Gestoppt"}
STATE_COLORS = {0: C_YELLOW, 1: C_GREEN, 2: C_YELLOW, 3: C_MUTED}


# ---------------------------------------------------------------------------
# Tray-Icon-Erzeugung
# ---------------------------------------------------------------------------

def _make_tray_icon(color: str, size: int = 64) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    draw.ellipse([2, 2, size - 2, size - 2], fill=(r, g, b, 255))
    cx = size // 2
    w2 = int(size * 0.30)
    h2 = int(size * 0.10)
    y_band = int(size * 0.62)
    draw.rounded_rectangle(
        [cx - w2, y_band - h2, cx + w2, y_band + h2],
        radius=h2, fill=(255, 255, 255, 200)
    )
    head_r = int(size * 0.09)
    draw.ellipse(
        [cx - head_r, int(size * 0.18) - head_r,
         cx + head_r, int(size * 0.18) + head_r],
        fill=(255, 255, 255, 210)
    )
    draw.line(
        [cx, int(size * 0.27), cx - int(size * 0.10), int(size * 0.50)],
        fill=(255, 255, 255, 200), width=max(2, size // 20)
    )
    draw.line(
        [cx, int(size * 0.27), cx + int(size * 0.10), int(size * 0.45)],
        fill=(255, 255, 255, 200), width=max(2, size // 20)
    )
    draw.line(
        [cx - int(size * 0.05), int(size * 0.42),
         cx - int(size * 0.14), int(size * 0.58)],
        fill=(255, 255, 255, 200), width=max(2, size // 20)
    )
    draw.line(
        [cx + int(size * 0.05), int(size * 0.38),
         cx + int(size * 0.14), int(size * 0.55)],
        fill=(255, 255, 255, 200), width=max(2, size // 20)
    )
    return img


# ---------------------------------------------------------------------------
# Haupt-App
# ---------------------------------------------------------------------------

class TreadmillTrayApp:
    def __init__(self):
        self.manager: Optional[BluetoothManager] = None
        self.treadmill_data: Optional[TreadmillData] = None
        self.connected = False
        self.running_state = -1        # -1 = nicht verbunden
        self.current_speed = 1000      # Laufband-Einheiten (1000 = 1,0 km/h)
        self.config = self._load_config()
        self._tray_icon: Optional[pystray.Icon] = None
        self._session_start_dist: Optional[int] = None
        self._sound_on: Optional[bool] = None

        # Historie-Session-Tracking
        self._session_start_time: Optional[datetime] = None
        self._hist_start_dist: Optional[int] = None
        self._hist_start_steps: int = 0
        self._hist_start_calories: int = 0
        self._session_target_speed: float = 0.0

        self.root = tk.Tk()
        self.root.title("PitPat Laufband")
        self.root.configure(bg=C_BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self._build_ui()
        self._setup_tray()
        self._update_loop()

    # ------------------------------------------------------------------
    # Konfiguration
    # ------------------------------------------------------------------

    def _load_config(self) -> dict:
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, encoding="utf-8") as f:
                    return json.load(f)
        except Exception as exc:
            LOGGER.warning("Konfiguration konnte nicht geladen werden: %s", exc)
        return {}

    def _save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
        except Exception as exc:
            LOGGER.warning("Konfiguration konnte nicht gespeichert werden: %s", exc)

    def _steps_for_data(self, data: TreadmillData) -> int:
        steps = data.steps
        if steps == 0 and data.real_electricity_steps is not None:
            steps = data.real_electricity_steps
        if steps == 0 and self._session_start_dist is not None:
            steps = _estimated_steps_from_distance(data.distance - self._session_start_dist)
        return steps

    # ------------------------------------------------------------------
    # UI-Hilfsmethoden
    # ------------------------------------------------------------------

    def _lbl(self, parent, text, font=("Segoe UI", 9), fg=C_MUTED, **kw):
        kw.setdefault("bg", parent["bg"])
        return tk.Label(parent, text=text, font=font, fg=fg, **kw)

    def _btn(self, parent, text, cmd, bg=C_PANEL, fg=C_FG, font=("Segoe UI", 10),
             width=None, state="normal", pady=6, **kw):
        kw.setdefault("activebackground", bg)
        kw.setdefault("activeforeground", fg)
        b = tk.Button(
            parent, text=text, command=cmd,
            bg=bg, fg=fg, relief="flat", font=font,
            cursor="hand2", state=state, pady=pady,
            **kw
        )
        if width:
            b.config(width=width)
        return b

    # ------------------------------------------------------------------
    # UI-Aufbau
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = self.root
        PAD = 10

        # ── Kopfzeile ──────────────────────────────────────────────
        hdr = tk.Frame(root, bg=C_BG, pady=8)
        hdr.pack(fill="x", padx=PAD)

        self._lbl(hdr, "🏃 PitPat Laufband", font=("Segoe UI", 13, "bold"),
                  fg=C_FG).pack(side="left")

        self.status_lbl = tk.Label(
            hdr, text="⬤  Nicht verbunden",
            font=("Segoe UI", 9), bg=C_BG, fg=C_RED
        )
        self.status_lbl.pack(side="right")

        # ── Verbindungs-Panel ──────────────────────────────────────
        conn = tk.Frame(root, bg=C_CARD, padx=PAD, pady=PAD)
        conn.pack(fill="x", padx=PAD, pady=(0, 6))

        addr_row = tk.Frame(conn, bg=C_CARD)
        addr_row.pack(fill="x")

        self.addr_var = tk.StringVar(value=self.config.get("last_address", ""))
        self.addr_entry = tk.Entry(
            addr_row, textvariable=self.addr_var,
            font=("Consolas", 10), bg="#0d1b2a", fg=C_FG,
            insertbackground=C_FG, relief="flat", bd=5, width=22
        )
        self.addr_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.scan_btn = self._btn(addr_row, "Suchen", self._scan_devices,
                                   font=("Segoe UI", 9), pady=4, padx=6)
        self.scan_btn.pack(side="right")

        self.connect_btn = self._btn(
            conn, "Verbinden", self._toggle_connect,
            bg=C_ACCENT, fg="#fff", font=("Segoe UI", 10, "bold"),
            pady=7, activebackground="#2070cc"
        )
        self.connect_btn.pack(fill="x", pady=(8, 0))

        # ── Statistik-Karten ───────────────────────────────────────
        stats = tk.Frame(root, bg=C_BG)
        stats.pack(fill="x", padx=PAD, pady=(0, 6))

        self.stat_vars: dict[str, tk.StringVar] = {}
        #              key         Titel             Init        row col cspan
        defs = [
            ("speed",    "Geschwindigkeit", "—  km/h",  0, 0, 1),
            ("distance", "Distanz",         "—  km",    0, 1, 1),
            ("duration", "Dauer",           "00:00:00", 0, 2, 1),
            ("steps",    "Schritte",        "—",        1, 0, 1),
            ("calories", "Kalorien",        "—  kcal",  1, 1, 2),
        ]
        for key, title, init, row, col, cspan in defs:
            card = tk.Frame(stats, bg=C_CARD, padx=10, pady=8)
            card.grid(row=row, column=col, columnspan=cspan,
                      padx=3, pady=3, sticky="nsew")
            stats.columnconfigure(col, weight=1)
            self._lbl(card, title).pack()
            v = tk.StringVar(value=init)
            self.stat_vars[key] = v
            tk.Label(card, textvariable=v,
                     font=("Segoe UI", 12, "bold"),
                     bg=C_CARD, fg=C_FG).pack()

        # ── Geschwindigkeit: Direkt-Buttons 1–6 + Feinschritte ─────
        spd_frame = tk.Frame(root, bg=C_CARD, padx=PAD, pady=8)
        spd_frame.pack(fill="x", padx=PAD, pady=(0, 6))

        # Header-Zeile mit Zielgeschwindigkeit
        spd_hdr = tk.Frame(spd_frame, bg=C_CARD)
        spd_hdr.pack(fill="x", pady=(0, 6))
        self._lbl(spd_hdr, "Zielgeschwindigkeit", bg=C_CARD).pack(side="left")
        self.target_speed_var = tk.StringVar(value="1,0  km/h")
        tk.Label(
            spd_hdr, textvariable=self.target_speed_var,
            font=("Segoe UI", 11, "bold"), bg=C_CARD, fg=C_ACCENT
        ).pack(side="right")

        # Direkt-Buttons 1–6 km/h
        km_row = tk.Frame(spd_frame, bg=C_CARD)
        km_row.pack(fill="x")
        self._speed_btns: dict[int, tk.Button] = {}
        for kmh in range(1, 7):
            sp = kmh * 1000
            btn = self._btn(
                km_row, str(kmh), lambda s=sp: self._set_speed_direct(s),
                bg=C_PANEL, fg=C_FG,
                font=("Segoe UI", 12, "bold"), pady=6, state="disabled"
            )
            btn.pack(side="left", expand=True, fill="x", padx=1)
            self._speed_btns[sp] = btn

        # Feinschritte ±0,1 km/h
        micro_row = tk.Frame(spd_frame, bg=C_CARD)
        micro_row.pack(fill="x", pady=(6, 0))

        self.speed_down01_btn = self._btn(
            micro_row, "− 0,1", self._speed_down01,
            font=("Segoe UI", 10), pady=4, state="disabled"
        )
        self.speed_down01_btn.pack(side="left", expand=True, fill="x", padx=(0, 2))

        self.speed_up01_btn = self._btn(
            micro_row, "+ 0,1", self._speed_up01,
            font=("Segoe UI", 10), pady=4, state="disabled"
        )
        self.speed_up01_btn.pack(side="right", expand=True, fill="x", padx=(2, 0))

        # ── Steuer-Buttons ─────────────────────────────────────────
        ctrl = tk.Frame(root, bg=C_BG)
        ctrl.pack(fill="x", padx=PAD, pady=(0, 4))

        self.start_btn = self._btn(
            ctrl, "Start", self._toggle_start,
            bg=C_GREEN, fg="#fff", font=("Segoe UI", 11, "bold"),
            pady=8, state="disabled", activebackground="#2d8a30"
        )
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))

        self.stop_btn = self._btn(
            ctrl, "Stop", self._stop,
            bg=C_RED, fg="#fff", font=("Segoe UI", 11, "bold"),
            pady=8, state="disabled", activebackground="#c62828"
        )
        self.stop_btn.pack(side="right", expand=True, fill="x", padx=(4, 0))

        # ── Ton + Historie ─────────────────────────────────────────
        sound_row = tk.Frame(root, bg=C_BG)
        sound_row.pack(fill="x", padx=PAD, pady=(0, PAD))

        self.sound_btn = self._btn(
            sound_row, "🔕 Stummschalten", self._toggle_sound,
            bg=C_PANEL, fg=C_FG, font=("Segoe UI", 10),
            pady=6, state="disabled"
        )
        self.sound_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        self._btn(
            sound_row, "📋 Historie", self._show_history,
            bg=C_PANEL, fg=C_FG, font=("Segoe UI", 10), pady=6
        ).pack(side="right", padx=(0, 0))

        # Fenster zentrieren
        w, h = 360, 560
        sw = root.winfo_screenwidth()
        sh = root.winfo_screenheight()
        root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    # ------------------------------------------------------------------
    # System Tray
    # ------------------------------------------------------------------

    def _setup_tray(self):
        menu = pystray.Menu(
            pystray.MenuItem("Fenster anzeigen",
                             lambda i, it: self.show_window(), default=True),
            pystray.MenuItem("Verbinden/Trennen",
                             lambda i, it: self.root.after(0, self._toggle_connect)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Beenden",
                             lambda i, it: self.root.after(0, self.quit)),
        )
        self._tray_icon = pystray.Icon(
            "PitPat",
            _make_tray_icon(C_RED),
            "PitPat Laufband\nNicht verbunden",
            menu
        )
        threading.Thread(target=self._tray_icon.run, daemon=True).start()

    def _refresh_tray(self):
        if not self._tray_icon:
            return
        if not self.connected:
            color, tip = C_RED, "PitPat Laufband\nNicht verbunden"
        elif self.running_state == 1:
            spd = self.current_speed / 1000
            color = C_GREEN
            tip = f"PitPat Laufband\nLäuft  {spd:.1f} km/h"
        elif self.running_state == 2:
            color, tip = C_YELLOW, "PitPat Laufband\nPausiert"
        else:
            color, tip = C_ACCENT, "PitPat Laufband\nVerbunden"
        try:
            self._tray_icon.icon = _make_tray_icon(color)
            self._tray_icon.title = tip
        except Exception as exc:
            LOGGER.debug("Tray-Icon konnte nicht aktualisiert werden: %s", exc)

    # ------------------------------------------------------------------
    # Fenster-Verwaltung
    # ------------------------------------------------------------------

    def hide_window(self):
        self.root.withdraw()

    def show_window(self):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # ------------------------------------------------------------------
    # Periodische UI-Aktualisierung
    # ------------------------------------------------------------------

    def _update_loop(self):
        self._refresh_ui()
        self.root.after(500, self._update_loop)

    def _refresh_ui(self):
        data = self.treadmill_data

        if not self.connected:
            self.status_lbl.config(text="⬤  Nicht verbunden", fg=C_RED)
            self.connect_btn.config(text="Verbinden", bg=C_ACCENT,
                                    activebackground="#2070cc", state="normal")
            self.addr_entry.config(state="normal")
            self.scan_btn.config(state="normal")
            self._set_controls("disabled")
            return

        # Verbunden
        self.addr_entry.config(state="disabled")
        self.scan_btn.config(state="disabled")
        self.connect_btn.config(text="Trennen", bg=C_RED,
                                activebackground="#c62828", state="normal")

        state_name  = STATE_NAMES.get(self.running_state, "Verbunden")
        state_color = STATE_COLORS.get(self.running_state, C_ACCENT)
        self.status_lbl.config(text=f"⬤  {state_name}", fg=state_color)

        self._set_controls("normal")

        if self.running_state == 1:
            self.start_btn.config(text="Pause", bg=C_YELLOW,
                                  activebackground="#c68a00")
        else:
            self.start_btn.config(text="Start", bg=C_GREEN,
                                  activebackground="#2d8a30")

        if data:
            speed_unit = "mph" if data.unit_mode == 1 else "km/h"
            dist_unit  = "mi"  if data.unit_mode == 1 else "km"

            self.stat_vars["speed"].set(
                f"{data.current_speed / 1000:.1f}  {speed_unit}"
            )
            self.stat_vars["distance"].set(
                f"{data.distance / 1000:.2f}  {dist_unit}"
            )
            self.stat_vars["calories"].set(f"{data.calories}  kcal")

            steps = self._steps_for_data(data)
            if data.steps == 0 and data.real_electricity_steps is None and self._session_start_dist is not None:
                # data.distance wird in der UI als Meter behandelt (÷1000 => km).
                # Daher hier _SCHRITT_LAENGE_M statt fälschlich 750 "mm" direkt.
                self.stat_vars["steps"].set(f"~{steps}")
            else:
                self.stat_vars["steps"].set(str(steps))

            secs = int(data.duration_seconds)
            h, m, s = secs // 3600, (secs % 3600) // 60, secs % 60
            self.stat_vars["duration"].set(f"{h:02d}:{m:02d}:{s:02d}")

        self.target_speed_var.set(f"{self.current_speed / 1000:.1f}  km/h")

        # Aktiven km/h-Button hervorheben
        for sp, btn in self._speed_btns.items():
            if sp == self.current_speed:
                btn.config(bg=C_ACCENT, fg="#fff", activebackground="#2070cc")
            else:
                btn.config(bg=C_PANEL, fg=C_FG, activebackground=C_PANEL)

        # Ton-Status aus Notification-Daten (Byte 47, Bit 0)
        if data and data.buzzer_control is not None:
            self._sound_on = (data.buzzer_control == 1)
        self._refresh_sound_button()

    def _set_controls(self, state: str):
        for btn in (self.start_btn, self.stop_btn,
                    self.speed_up01_btn, self.speed_down01_btn,
                    self.sound_btn):
            btn.config(state=state)
        for sp, btn in self._speed_btns.items():
            if state == "disabled":
                btn.config(state=state, bg=C_PANEL, fg=C_FG)
            else:
                btn.config(state=state)

    # ------------------------------------------------------------------
    # Bluetooth
    # ------------------------------------------------------------------

    def _toggle_connect(self):
        if self.connected:
            self._disconnect()
        else:
            addr = self.addr_var.get().strip()
            if not addr:
                messagebox.showwarning(
                    "Keine Adresse",
                    "Bitte eine Bluetooth-Adresse eingeben oder per Scan auswählen."
                )
                return
            self._connect(addr)

    def _connect(self, address: str):
        self.connect_btn.config(state="disabled", text="Verbinde…")
        self.config["last_address"] = address
        self._save_config()

        def do_connect():
            mgr = BluetoothManager(
                address,
                on_disconnect=self._on_ble_disconnect,
                on_receive=self._on_ble_receive,
            )
            ok = mgr.connect()
            if ok:
                self.manager = mgr
                self.connected = True
                self.running_state = 3
            else:
                mgr.shutdown()
                self.connected = False
            self.root.after(0, self._refresh_tray)

        threading.Thread(target=do_connect, daemon=True).start()

    def _disconnect(self):
        if self._session_start_time is not None and self.treadmill_data is not None:
            self._save_session(self.treadmill_data)
        self._session_start_time = None
        self._hist_start_dist = None

        mgr = self.manager
        self.manager = None
        self.connected = False
        self.treadmill_data = None
        self.running_state = -1
        if mgr:
            threading.Thread(target=mgr.shutdown, daemon=True).start()
        self._refresh_tray()

    def _on_ble_disconnect(self, address: str):
        self.connected = False
        self.treadmill_data = None
        self.running_state = -1
        self.manager = None
        self.root.after(0, self._refresh_tray)

    def _on_ble_receive(self, data: TreadmillData):
        prev_state = self.running_state
        self.treadmill_data = data
        self.running_state = data.running_state
        if data.current_speed > 0:
            self.current_speed = data.current_speed

        # Schritt-Schätzung (bestehende Logik, unverändert)
        if data.running_state == 1 and prev_state != 1:
            self._session_start_dist = data.distance
        elif data.running_state in (2, 3) and prev_state == 1:
            self._session_start_dist = None

        # Historie-Session-Tracking
        if data.running_state == 1 and prev_state not in (1, 2):
            # Frischer Start (nicht Fortsetzen nach Pause)
            self._session_start_time = datetime.now()
            self._session_target_speed = self.current_speed / 1000
            self._hist_start_dist = data.distance
            self._hist_start_steps = self._steps_for_data(data)
            self._hist_start_calories = data.calories
        elif data.running_state == 3 and prev_state in (0, 1, 2) and self._session_start_time is not None:
            self._save_session(data)
            self._session_start_time = None
            self._hist_start_dist = None

        self.root.after(0, self._refresh_tray)

    # ------------------------------------------------------------------
    # Steuer-Aktionen
    # ------------------------------------------------------------------

    def _send(self, packet: bytes):
        mgr = self.manager
        if mgr:
            threading.Thread(
                target=lambda: mgr.send_data(packet), daemon=True
            ).start()

    def _toggle_start(self):
        if self.running_state == 1:
            self._send(TreadmillController.pause())
        else:
            self._send(TreadmillController.start(self.current_speed))

    def _stop(self):
        self._send(TreadmillController.stop())

    def _toggle_sound(self):
        # Robust auch bei unbekanntem Startstatus: erster Klick schaltet stumm,
        # danach ist das Verhalten ein klarer Toggle.
        if self._sound_on is False:
            self._send(TreadmillController.sound_on())
            self._sound_on = True
        else:
            self._send(TreadmillController.sound_off())
            self._sound_on = False
        self._refresh_sound_button()

    def _refresh_sound_button(self):
        if self._sound_on is True:
            self.sound_btn.config(
                text="🔕 Stummschalten",
                bg=C_PANEL,
                fg=C_FG,
                activebackground=C_PANEL,
            )
        elif self._sound_on is False:
            self.sound_btn.config(
                text="🔔 Ton einschalten",
                bg=C_ACCENT,
                fg="#fff",
                activebackground="#2070cc",
            )
        else:
            self.sound_btn.config(
                text="🔕 Stummschalten",
                bg=C_PANEL,
                fg=C_FG,
                activebackground=C_PANEL,
            )

    def _set_speed_direct(self, speed_units: int):
        self.current_speed = speed_units
        self._apply_speed()

    def _speed_up01(self):
        self.current_speed = min(self.current_speed + 100, 6000)
        self._apply_speed()

    def _speed_down01(self):
        self.current_speed = max(self.current_speed - 100, 1000)
        self._apply_speed()

    def _apply_speed(self):
        self.target_speed_var.set(f"{self.current_speed / 1000:.1f}  km/h")
        if self.manager and self.running_state == 1:
            self._send(TreadmillController.set_speed(self.current_speed))

    # ------------------------------------------------------------------
    # Workout-Historie
    # ------------------------------------------------------------------

    def _save_session(self, data: TreadmillData):
        if self._session_start_time is None:
            return

        distance_delta = max(0, data.distance - (self._hist_start_dist or 0))
        total_steps = self._steps_for_data(data)
        if total_steps == 0 and self._hist_start_dist is not None:
            total_steps = self._hist_start_steps + _estimated_steps_from_distance(distance_delta)
        steps_delta = max(0, total_steps - self._hist_start_steps)
        calories_delta = max(0, data.calories - self._hist_start_calories)
        duration_s = max(0, int(data.duration_seconds))
        avg_speed = (distance_delta / 1000) / (duration_s / 3600) if duration_s > 0 else 0.0

        entry = make_entry(
            start_time=self._session_start_time,
            duration_s=duration_s,
            distance_km=distance_delta / 1000,
            steps=steps_delta,
            calories=calories_delta,
            avg_speed_kmh=avg_speed,
            target_speed_kmh=self._session_target_speed or (self.current_speed / 1000),
            unit_mode=data.unit_mode,
        )
        save_entry(entry)

    def _show_history(self):
        history = list(reversed(load_history()))

        win = tk.Toplevel(self.root)
        win.title("Workout-Historie")
        win.configure(bg=C_BG)
        win.geometry("520x420")
        win.transient(self.root)

        header = tk.Frame(win, bg=C_BG, pady=10)
        header.pack(fill="x", padx=10)
        self._lbl(header, "📋 Letzte Läufe", font=("Segoe UI", 12, "bold"), fg=C_FG).pack(side="left")
        self._lbl(header, f"{len(history)} Einträge", font=("Segoe UI", 9), fg=C_MUTED).pack(side="right")

        body = tk.Frame(win, bg=C_CARD, padx=8, pady=8)
        body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        text = tk.Text(
            body,
            bg="#0d1b2a",
            fg=C_FG,
            relief="flat",
            wrap="word",
            font=("Consolas", 9),
            padx=8,
            pady=8,
            height=16,
        )
        scroll = tk.Scrollbar(body, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

        if not history:
            text.insert("end", "Noch keine Läufe gespeichert.\n\nSobald du ein Workout startest und wieder stoppst, erscheint es hier.")
        else:
            for idx, item in enumerate(history[:30], start=1):
                started = item.get("start_time", "")
                try:
                    started = datetime.fromisoformat(started).strftime("%d.%m.%Y %H:%M")
                except Exception:
                    started = str(started)
                duration_s = int(item.get("duration_s", 0))
                h, m, s = duration_s // 3600, (duration_s % 3600) // 60, duration_s % 60
                duration = f"{h:02d}:{m:02d}:{s:02d}"
                text.insert(
                    "end",
                    f"{idx:02d}. {started}\n"
                    f"    Dauer: {duration} | Distanz: {item.get('distance_km', 0):.2f} km | Schritte: {item.get('steps', 0)}\n"
                    f"    Kalorien: {item.get('calories', 0)} kcal | Ø: {item.get('avg_speed_kmh', 0):.1f} km/h | Ziel: {item.get('target_speed_kmh', 0):.1f} km/h\n\n",
                )
        text.config(state="disabled")

        btn_row = tk.Frame(win, bg=C_BG)
        btn_row.pack(fill="x", padx=10, pady=(0, 10))
        self._btn(btn_row, "Schließen", win.destroy, bg=C_ACCENT, fg="#fff", pady=6).pack(side="right")

    # ------------------------------------------------------------------
    # Geräte-Scan
    # ------------------------------------------------------------------

    def _scan_devices(self):
        win = tk.Toplevel(self.root)
        win.title("Bluetooth-Gerät suchen")
        win.configure(bg=C_BG)
        win.geometry("380x300")
        win.transient(self.root)
        win.grab_set()

        tk.Label(
            win, text="Suche nach Bluetooth-Geräten (5 Sek.)…",
            font=("Segoe UI", 10), bg=C_BG, fg=C_FG, pady=10
        ).pack()

        lb = tk.Listbox(
            win, bg="#0d1b2a", fg=C_FG, font=("Consolas", 9),
            selectbackground=C_ACCENT, relief="flat", bd=4, height=10
        )
        lb.pack(fill="both", expand=True, padx=10)
        lb.insert("end", "Scanne…")

        def on_select(event=None):
            sel = lb.curselection()
            if not sel:
                return
            line: str = lb.get(sel[0])
            if "(" in line:
                addr = line.rsplit("(", 1)[-1].rstrip(")")
                self.addr_var.set(addr)
            win.destroy()

        lb.bind("<Double-Button-1>", on_select)

        btn_row = tk.Frame(win, bg=C_BG)
        btn_row.pack(fill="x", padx=10, pady=8)
        self._btn(btn_row, "Auswählen", on_select,
                  bg=C_ACCENT, fg="#fff").pack(side="left")
        self._btn(btn_row, "Abbrechen", win.destroy).pack(side="right")

        async def do_scan():
            try:
                devices = await BleakScanner.discover(timeout=5.0)
                win.after(0, lambda: _show(devices))
            except Exception as e:
                win.after(0, lambda: _show_err(str(e)))

        def _show(devices):
            lb.delete(0, "end")
            for d in sorted(devices, key=lambda x: (x.name or "").lower()):
                lb.insert("end", f"{d.name or 'Unbekannt'}  ({d.address})")
            if not devices:
                lb.insert("end", "Keine Geräte gefunden")

        def _show_err(msg):
            lb.delete(0, "end")
            lb.insert("end", f"Fehler: {msg}")

        threading.Thread(target=lambda: asyncio.run(do_scan()), daemon=True).start()

    # ------------------------------------------------------------------
    # Beenden
    # ------------------------------------------------------------------

    def quit(self):
        if self.manager:
            try:
                self.manager.shutdown()
            except Exception as exc:
                LOGGER.warning("Manager-Shutdown beim Beenden fehlgeschlagen: %s", exc)
        if self._tray_icon:
            try:
                self._tray_icon.stop()
            except Exception as exc:
                LOGGER.warning("Tray-Stop beim Beenden fehlgeschlagen: %s", exc)
        try:
            self.root.quit()
            self.root.destroy()
        except Exception as exc:
            LOGGER.warning("Fenster konnte nicht sauber geschlossen werden: %s", exc)

    # ------------------------------------------------------------------
    # Start
    # ------------------------------------------------------------------

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = TreadmillTrayApp()
    app.run()
