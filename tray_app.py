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

import customtkinter as ctk
import pystray
from PIL import Image, ImageDraw
from bleak import BleakScanner

from bluetooth_manager_fba import BluetoothManagerFBA as BluetoothManager
from treadmill_controller import TreadmillController
from treadmill_data import TreadmillData
from workout_history import load_history, save_entry, make_entry

CONFIG_FILE = Path(__file__).parent / "config.json"
LOGGER = logging.getLogger(__name__)

_SCHRITT_LAENGE_M = 0.51


def _estimated_steps_from_distance(dist_m: int) -> int:
    return int(max(0, dist_m) / _SCHRITT_LAENGE_M)


# --- Farben (dezentes Dark Theme, entsaettigt) ---
C_BG      = "#1c1d22"
C_CARD    = "#24252c"
C_PANEL   = "#2d2f38"
C_FG      = "#d6d6da"
C_MUTED   = "#84868f"
C_ACCENT  = "#5b7fa6"
C_ACCENT_H = "#4d6c8f"
C_GREEN   = "#5a9e6f"
C_GREEN_H = "#4c8a5f"
C_YELLOW  = "#c99a4a"
C_YELLOW_H = "#b3863c"
C_RED     = "#b5555a"
C_RED_H   = "#9c464b"

STATE_NAMES  = {0: "Startet", 1: "Läuft", 2: "Pausiert", 3: "Gestoppt"}
STATE_COLORS = {0: C_YELLOW, 1: C_GREEN, 2: C_YELLOW, 3: C_MUTED}

ctk.set_appearance_mode("dark")


def _font(size: int, weight: str = "normal", family: str = "Segoe UI") -> ctk.CTkFont:
    # CTkFont (statt eines rohen Font-Tupels) sorgt fuer korrektes
    # DPI-/Widget-Scaling -- mit rohen Tupeln wirkte fette, groessere
    # Schrift (z.B. der Titel) auf manchen Systemen "gestaucht".
    return ctk.CTkFont(family=family, size=size, weight=weight)


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
    _WINDOW_WIDTH = 360

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

        self.root = ctk.CTk()
        self.root.title("PitPat Laufband")
        self.root.configure(fg_color=C_BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)

        self._build_ui()
        self._setup_tray()
        self._update_loop()
        self.root.after(400, self._maybe_autoconnect)

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
    # UI-Aufbau
    # ------------------------------------------------------------------

    def _build_ui(self):
        root = self.root
        PAD = 12

        # -- Kopfzeile --
        hdr = ctk.CTkFrame(root, fg_color="transparent")
        hdr.pack(fill="x", padx=PAD, pady=(PAD, 6))

        ctk.CTkLabel(
            hdr, text="PitPat Laufband",
            font=_font(14, "bold"), text_color=C_FG
        ).pack(side="left")

        self.status_lbl = ctk.CTkLabel(
            hdr, text="●  Nicht verbunden",
            font=_font(10), text_color=C_MUTED
        )
        self.status_lbl.pack(side="right")

        # -- Verbindungs-Karte --
        # Zwei Ansichten: die volle Karte (Adresse/Suchen/Verbinden) wird nur
        # benoetigt, solange keine Verbindung besteht. Sobald verbunden ist,
        # ersetzt eine einzeilige, kompakte Ansicht die Karte -- der
        # Verbindungsstatus selbst steht bereits in der Kopfzeile.
        conn = ctk.CTkFrame(root, fg_color=C_CARD, corner_radius=10)
        conn.pack(fill="x", padx=PAD, pady=(0, 8))
        self._conn_card = conn
        self._conn_expanded = True

        self._auto_connect_var = tk.BooleanVar(value=bool(self.config.get("auto_connect", False)))

        # -- Volle Ansicht (nicht verbunden) --
        self.conn_full = ctk.CTkFrame(conn, fg_color="transparent")
        self.conn_full.pack(fill="x", padx=12, pady=12)

        addr_row = ctk.CTkFrame(self.conn_full, fg_color="transparent")
        addr_row.pack(fill="x")

        self.addr_var = tk.StringVar(value=self.config.get("last_address", ""))
        self.addr_entry = ctk.CTkEntry(
            addr_row, textvariable=self.addr_var,
            font=_font(10, family="Consolas"), fg_color="#15161a", text_color=C_FG,
            border_width=0, corner_radius=6
        )
        self.addr_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.scan_btn = ctk.CTkButton(
            addr_row, text="Suchen", command=self._scan_devices,
            font=_font(9), fg_color="transparent",
            hover_color=C_PANEL, text_color=C_MUTED,
            border_width=1, border_color=C_PANEL,
            corner_radius=6, width=70, height=28
        )
        self.scan_btn.pack(side="right")

        self.connect_btn = ctk.CTkButton(
            self.conn_full, text="Verbinden", command=self._toggle_connect,
            fg_color=C_ACCENT, hover_color=C_ACCENT_H, text_color="#fff",
            font=_font(10, "bold"), corner_radius=6, height=34
        )
        self.connect_btn.pack(fill="x", pady=(8, 8))

        autoconn_row = ctk.CTkFrame(self.conn_full, fg_color="transparent")
        autoconn_row.pack(fill="x")
        self.autoconn_switch = ctk.CTkSwitch(
            autoconn_row, text="Beim Start automatisch verbinden",
            variable=self._auto_connect_var, command=self._on_autoconnect_toggle,
            font=_font(9), text_color=C_MUTED,
            progress_color=C_ACCENT, button_color=C_FG, button_hover_color=C_FG,
            fg_color=C_PANEL
        )
        self.autoconn_switch.pack(side="left")

        # -- Kompakte Ansicht (verbunden): nur noch eine Zeile --
        self.conn_compact = ctk.CTkFrame(conn, fg_color="transparent")

        self.autoconn_switch_compact = ctk.CTkSwitch(
            self.conn_compact, text="Auto-Connect",
            variable=self._auto_connect_var, command=self._on_autoconnect_toggle,
            font=_font(9), text_color=C_MUTED,
            progress_color=C_ACCENT, button_color=C_FG, button_hover_color=C_FG,
            fg_color=C_PANEL
        )
        self.autoconn_switch_compact.pack(side="left", padx=12, pady=10)

        self.disconnect_btn = ctk.CTkButton(
            self.conn_compact, text="Trennen", command=self._toggle_connect,
            fg_color="transparent", hover_color=C_PANEL, text_color=C_MUTED,
            border_width=1, border_color=C_PANEL,
            font=_font(9), corner_radius=6, width=70, height=28
        )
        self.disconnect_btn.pack(side="right", padx=12, pady=10)

        # -- Statistik-Karten --
        stats = ctk.CTkFrame(root, fg_color="transparent")
        stats.pack(fill="x", padx=PAD, pady=(0, 8))

        self.stat_vars: dict[str, tk.StringVar] = {}
        # data.current_speed ist der vom Laufband live gemeldete Ist-Wert,
        # kein berechneter Durchschnitt -- daher die explizite Beschriftung.
        defs = [
            ("duration", "Dauer",                      "00:00:00", 0, 0, 2),
            ("steps",    "Schritte",                    "—",        1, 0, 1),
            ("distance", "Distanz",                     "—  km",    1, 1, 1),
            ("speed",    "Geschwindigkeit (aktuell)",   "—  km/h",  2, 0, 1),
            ("calories", "Kalorien",                    "—  kcal",  2, 1, 1),
        ]
        for key, title, init, row, col, cspan in defs:
            card = ctk.CTkFrame(stats, fg_color=C_CARD, corner_radius=10)
            card.grid(row=row, column=col, columnspan=cspan,
                      padx=3, pady=3, sticky="nsew")
            stats.columnconfigure(col, weight=1)
            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(padx=10, pady=8)
            ctk.CTkLabel(inner, text=title, font=_font(9), text_color=C_MUTED).pack()
            v = tk.StringVar(value=init)
            self.stat_vars[key] = v
            ctk.CTkLabel(inner, textvariable=v, font=_font(20, "bold"),
                         text_color=C_FG).pack()

        # -- Geschwindigkeit: Direkt-Buttons 1–6 + Feinschritte ─────
        spd_frame = ctk.CTkFrame(root, fg_color=C_CARD, corner_radius=10)
        spd_frame.pack(fill="x", padx=PAD, pady=(0, 8))
        spd_inner = ctk.CTkFrame(spd_frame, fg_color="transparent")
        spd_inner.pack(fill="x", padx=12, pady=10)

        spd_hdr = ctk.CTkFrame(spd_inner, fg_color="transparent")
        spd_hdr.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(spd_hdr, text="Zielgeschwindigkeit", font=_font(9),
                     text_color=C_MUTED).pack(side="left")
        self.target_speed_var = tk.StringVar(value="1,0  km/h")
        ctk.CTkLabel(spd_hdr, textvariable=self.target_speed_var,
                     font=_font(11, "bold"), text_color=C_ACCENT).pack(side="right")

        km_row = ctk.CTkFrame(spd_inner, fg_color="transparent")
        km_row.pack(fill="x")
        self._speed_btns: dict[int, ctk.CTkButton] = {}
        for kmh in range(1, 7):
            sp = kmh * 1000
            btn = ctk.CTkButton(
                km_row, text=str(kmh), command=lambda s=sp: self._set_speed_direct(s),
                fg_color=C_PANEL, hover_color=C_ACCENT_H, text_color=C_FG,
                font=_font(11, "bold"), corner_radius=6, height=36, width=30,
                state="disabled"
            )
            btn.pack(side="left", expand=True, fill="x", padx=1)
            self._speed_btns[sp] = btn

        micro_row = ctk.CTkFrame(spd_inner, fg_color="transparent")
        micro_row.pack(fill="x", pady=(6, 0))

        self.speed_down01_btn = ctk.CTkButton(
            micro_row, text="− 0,1", command=self._speed_down01,
            fg_color=C_PANEL, hover_color=C_ACCENT_H, text_color=C_FG,
            font=_font(9), corner_radius=6, height=28, state="disabled"
        )
        self.speed_down01_btn.pack(side="left", expand=True, fill="x", padx=(0, 2))

        self.speed_up01_btn = ctk.CTkButton(
            micro_row, text="+ 0,1", command=self._speed_up01,
            fg_color=C_PANEL, hover_color=C_ACCENT_H, text_color=C_FG,
            font=_font(9), corner_radius=6, height=28, state="disabled"
        )
        self.speed_up01_btn.pack(side="right", expand=True, fill="x", padx=(2, 0))

        # -- Steuer-Buttons --
        ctrl = ctk.CTkFrame(root, fg_color="transparent")
        ctrl.pack(fill="x", padx=PAD, pady=(0, 6))

        self.start_btn = ctk.CTkButton(
            ctrl, text="Start", command=self._toggle_start,
            fg_color=C_GREEN, hover_color=C_GREEN_H, text_color="#fff",
            font=_font(11, "bold"), corner_radius=6, height=38, state="disabled"
        )
        self.start_btn.pack(side="left", expand=True, fill="x", padx=(0, 4))

        self.stop_btn = ctk.CTkButton(
            ctrl, text="Stop", command=self._stop,
            fg_color=C_RED, hover_color=C_RED_H, text_color="#fff",
            font=_font(11, "bold"), corner_radius=6, height=38, state="disabled"
        )
        self.stop_btn.pack(side="right", expand=True, fill="x", padx=(4, 0))

        # -- Ton + Historie --
        sound_row = ctk.CTkFrame(root, fg_color="transparent")
        sound_row.pack(fill="x", padx=PAD, pady=(0, PAD))

        self.sound_btn = ctk.CTkButton(
            sound_row, text="Stummschalten", command=self._toggle_sound,
            fg_color=C_PANEL, hover_color=C_ACCENT_H, text_color=C_FG,
            font=_font(9), corner_radius=6, height=32, state="disabled"
        )
        self.sound_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        ctk.CTkButton(
            sound_row, text="Historie", command=self._show_history,
            fg_color="transparent", hover_color=C_PANEL, text_color=C_MUTED,
            border_width=1, border_color=C_PANEL,
            font=_font(9), corner_radius=6, height=32
        ).pack(side="right", fill="x", expand=True, padx=(4, 0))

        self._autosize_window(recenter=True)

    def _autosize_window(self, recenter: bool = False):
        # resizable(False, False) verhindert nur manuelles Ziehen durch die
        # Nutzerin -- programmatisch darf die Fenstergroesse weiterhin an den
        # tatsaechlich benoetigten Platz angepasst werden (z.B. wenn die
        # Verbindungskarte auf eine Zeile zusammenklappt).
        root = self.root
        root.update_idletasks()
        w = self._WINDOW_WIDTH
        h = root.winfo_reqheight()
        if recenter:
            sw = root.winfo_screenwidth()
            sh = root.winfo_screenheight()
            x = (sw - w) // 2
            y = (sh - h) // 2
        else:
            x = root.winfo_x()
            y = root.winfo_y()
        # Kurzes Umschalten von resizable erzwingt auf manchen Windows-
        # Systemen (v.a. bei abweichender Anzeigeskalierung) einen echten
        # Neuzeichnen-Zyklus des Fensterrahmens -- ohne das blieb beim
        # Verkleinern unten manchmal ein leerer Reststreifen der alten
        # Fenstergroesse stehen, der nicht sauber weggezeichnet wurde.
        root.resizable(True, True)
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.resizable(False, False)

        # Direkt nach dem Pack-Wechsel liefert winfo_reqheight() auf manchen
        # Systemen noch einen zu grossen Zwischenwert, bevor die Layout-
        # Engine final durchgerechnet hat. Ein zweiter Messpunkt nach einem
        # weiteren Idle-Tick korrigiert das.
        root.update_idletasks()
        corrected_h = root.winfo_reqheight()
        if corrected_h != h:
            root.resizable(True, True)
            root.geometry(f"{w}x{corrected_h}+{x}+{y}")
            root.resizable(False, False)

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

    def _set_connection_view(self, expanded: bool):
        if self._conn_expanded == expanded:
            return
        self._conn_expanded = expanded
        if expanded:
            self.conn_compact.pack_forget()
            self.conn_full.pack(fill="x", padx=12, pady=12)
        else:
            self.conn_full.pack_forget()
            self.conn_compact.pack(fill="x")
        self._autosize_window()

    # ------------------------------------------------------------------
    # Auto-Connect
    # ------------------------------------------------------------------

    def _on_autoconnect_toggle(self):
        self.config["auto_connect"] = bool(self._auto_connect_var.get())
        self._save_config()

    def _maybe_autoconnect(self):
        addr = self.addr_var.get().strip()
        if self.config.get("auto_connect") and addr and not self.connected:
            self._connect(addr)

    # ------------------------------------------------------------------
    # Periodische UI-Aktualisierung
    # ------------------------------------------------------------------

    def _update_loop(self):
        self._refresh_ui()
        self.root.after(500, self._update_loop)

    def _refresh_ui(self):
        data = self.treadmill_data
        self._set_connection_view(expanded=not self.connected)

        if not self.connected:
            self.status_lbl.configure(text="●  Nicht verbunden", text_color=C_MUTED)
            self.connect_btn.configure(text="Verbinden", fg_color=C_ACCENT,
                                        hover_color=C_ACCENT_H, state="normal")
            self.addr_entry.configure(state="normal")
            self.scan_btn.configure(state="normal")
            self._set_controls("disabled")
            return

        state_name  = STATE_NAMES.get(self.running_state, "Verbunden")
        state_color = STATE_COLORS.get(self.running_state, C_ACCENT)
        self.status_lbl.configure(text=f"●  {state_name}", text_color=state_color)

        self._set_controls("normal")

        if self.running_state == 1:
            self.start_btn.configure(text="Pause", fg_color=C_YELLOW, hover_color=C_YELLOW_H)
        else:
            self.start_btn.configure(text="Start", fg_color=C_GREEN, hover_color=C_GREEN_H)

        if data:
            speed_unit = "mph" if data.unit_mode == 1 else "km/h"
            dist_unit  = "mi"  if data.unit_mode == 1 else "km"

            self.stat_vars["speed"].set(f"{data.current_speed / 1000:.1f}  {speed_unit}")
            self.stat_vars["distance"].set(f"{data.distance / 1000:.2f}  {dist_unit}")
            self.stat_vars["calories"].set(f"{data.calories}  kcal")

            steps = self._steps_for_data(data)
            if data.steps == 0 and data.real_electricity_steps is None and self._session_start_dist is not None:
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
                btn.configure(fg_color=C_ACCENT, text_color="#fff", hover_color=C_ACCENT_H)
            else:
                btn.configure(fg_color=C_PANEL, text_color=C_FG, hover_color=C_ACCENT_H)

        # Ton-Status aus Notification-Daten (Byte 47, Bit 0)
        if data and data.buzzer_control is not None:
            self._sound_on = (data.buzzer_control == 1)
        self._refresh_sound_button()

    def _set_controls(self, state: str):
        for btn in (self.start_btn, self.stop_btn,
                    self.speed_up01_btn, self.speed_down01_btn,
                    self.sound_btn):
            btn.configure(state=state)
        for sp, btn in self._speed_btns.items():
            if state == "disabled":
                btn.configure(state=state, fg_color=C_PANEL, text_color=C_FG)
            else:
                btn.configure(state=state)

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
        self.connect_btn.configure(state="disabled", text="Verbinde...")
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
        # Das Laufband meldet seinen Ton-Status nicht zuverlässig direkt nach dem
        # Verbinden (buzzer_control kommt erst mit einem späteren Notify-Paket,
        # falls überhaupt). Solange der echte Zustand unbekannt ist, darf der
        # Button also nicht "Stummschalten"/"Ton einschalten" vorgaukeln, sondern
        # zeigt sich neutral als reiner Toggle.
        if self._sound_on is True:
            self.sound_btn.configure(text="Stummschalten", fg_color=C_PANEL,
                                      text_color=C_FG, hover_color=C_ACCENT_H)
        elif self._sound_on is False:
            self.sound_btn.configure(text="Ton einschalten", fg_color=C_ACCENT,
                                      text_color="#fff", hover_color=C_ACCENT_H)
        else:
            self.sound_btn.configure(text="Ton umschalten", fg_color=C_PANEL,
                                      text_color=C_FG, hover_color=C_ACCENT_H)

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

        win = ctk.CTkToplevel(self.root)
        win.title("Workout-Historie")
        win.configure(fg_color=C_BG)
        win.geometry("520x460")
        win.transient(self.root)

        header = ctk.CTkFrame(win, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(14, 8))
        ctk.CTkLabel(header, text="Letzte Läufe", font=_font(12, "bold"),
                     text_color=C_FG).pack(side="left")
        ctk.CTkLabel(header, text=f"{len(history)} Einträge", font=_font(9),
                     text_color=C_MUTED).pack(side="right")

        body = ctk.CTkScrollableFrame(win, fg_color=C_CARD, corner_radius=10)
        body.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        if not history:
            ctk.CTkLabel(
                body, justify="left", text_color=C_MUTED, font=_font(10),
                text="Noch keine Läufe gespeichert.\n\nSobald du ein Workout startest "
                     "und wieder stoppst, erscheint es hier."
            ).pack(padx=10, pady=10, anchor="w")
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

                row = ctk.CTkFrame(body, fg_color=C_PANEL, corner_radius=8)
                row.pack(fill="x", padx=4, pady=3)
                inner = ctk.CTkFrame(row, fg_color="transparent")
                inner.pack(fill="x", padx=10, pady=8)

                ctk.CTkLabel(inner, text=f"{idx:02d}. {started}", font=_font(10, "bold"),
                             text_color=C_FG, anchor="w").pack(fill="x")
                ctk.CTkLabel(
                    inner, anchor="w", justify="left", text_color=C_MUTED,
                    font=_font(9, family="Consolas"),
                    text=(f"Dauer {duration}  |  Distanz {item.get('distance_km', 0):.2f} km  "
                          f"|  Schritte {item.get('steps', 0)}\n"
                          f"Kalorien {item.get('calories', 0)} kcal  "
                          f"|  Ø {item.get('avg_speed_kmh', 0):.1f} km/h  "
                          f"|  Ziel {item.get('target_speed_kmh', 0):.1f} km/h")
                ).pack(fill="x", pady=(2, 0))

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(btn_row, text="Schließen", command=win.destroy,
                      fg_color=C_ACCENT, hover_color=C_ACCENT_H, text_color="#fff",
                      corner_radius=6, height=32).pack(side="right")

    # ------------------------------------------------------------------
    # Geräte-Scan
    # ------------------------------------------------------------------

    def _scan_devices(self):
        win = ctk.CTkToplevel(self.root)
        win.title("Bluetooth-Gerät suchen")
        win.configure(fg_color=C_BG)
        win.geometry("380x320")
        win.transient(self.root)
        win.grab_set()

        ctk.CTkLabel(
            win, text="Suche nach Bluetooth-Geräten (5 Sek.)...",
            font=_font(10), text_color=C_FG
        ).pack(pady=(14, 8))

        list_frame = ctk.CTkScrollableFrame(win, fg_color=C_CARD, corner_radius=10)
        list_frame.pack(fill="both", expand=True, padx=14)

        status_lbl = ctk.CTkLabel(list_frame, text="Scanne...", text_color=C_MUTED,
                                   font=_font(9))
        status_lbl.pack(padx=10, pady=10, anchor="w")

        def pick(addr: str):
            self.addr_var.set(addr)
            win.destroy()

        def _show(devices):
            status_lbl.destroy()
            if not devices:
                ctk.CTkLabel(list_frame, text="Keine Geräte gefunden",
                             text_color=C_MUTED, font=_font(9)).pack(padx=10, pady=10)
                return
            for d in sorted(devices, key=lambda x: (x.name or "").lower()):
                name = d.name or "Unbekannt"
                row = ctk.CTkButton(
                    list_frame, text=f"{name}   ({d.address})",
                    anchor="w", command=lambda a=d.address: pick(a),
                    fg_color=C_PANEL, hover_color=C_ACCENT_H, text_color=C_FG,
                    font=_font(9, family="Consolas"), corner_radius=6, height=32
                )
                row.pack(fill="x", padx=4, pady=2)

        def _show_err(msg):
            status_lbl.configure(text=f"Fehler: {msg}")

        async def do_scan():
            try:
                devices = await BleakScanner.discover(timeout=5.0)
                win.after(0, lambda: _show(devices))
            except Exception as e:
                win.after(0, lambda: _show_err(str(e)))

        btn_row = ctk.CTkFrame(win, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=10)
        ctk.CTkButton(btn_row, text="Abbrechen", command=win.destroy,
                      fg_color="transparent", hover_color=C_PANEL, text_color=C_MUTED,
                      border_width=1, border_color=C_PANEL, corner_radius=6).pack(side="right")

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
