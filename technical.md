# technical.md

This file contains the more technical documentation for PitPat Treadmill Tray.

## Project goal

PitPat Treadmill Tray is a compact Windows tray app for controlling a PitPat treadmill BA09-B over Bluetooth Low Energy (BLE).

The main goal is a simple user experience for normal Windows users, not a feature-heavy fitness dashboard.

## Main features

- Windows tray UI
- BLE device scan and connect
- start / pause / stop
- direct speed buttons from 1 to 6 km/h
- fine adjustment with ±0.1 km/h
- verified sound mute / unmute support
- local workout history

## Project structure

```text
tray_app.py              Main Windows tray UI
bluetooth_manager_fba.py BLE connection / notifications / writes
treadmill_controller.py  Packet generation for treadmill commands
treadmill_data.py        Payload parsing / telemetry decoding
workout_history.py       Local persistent workout history
__main__.py              Alternate Python entry point
build-release.sh         Helper script for PyInstaller builds
treadmill-tray.spec      Canonical PyInstaller spec
docs/
  reference/
    hex-commands.md
  screenshots/
```

## Requirements

- Windows
- Python 3.11+
- Bluetooth adapter with BLE support

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## Run locally

```bash
python tray_app.py
```

Alternative entry point:

```bash
python __main__.py
```

## Build

Quick build:

```bash
bash build-release.sh
```

Manual build:

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name treadmill-tray tray_app.py
```

Expected output:

- `dist/treadmill-tray.exe`

## Persistence

Config (`config.json`) and workout history (`workout_history.json`) are
stored right next to `treadmill-tray.exe` (or next to the script in dev
mode) — the app is portable, so both files travel with the folder it runs
from rather than living in `%APPDATA%`.

Stored fields may include:
- start time
- duration
- distance
- steps
- calories
- average speed
- target speed

## BLE / protocol notes

The currently used BLE path is the FBA service family.

See:
- [docs/reference/hex-commands.md](docs/reference/hex-commands.md)

That document includes:
- UUIDs
- packet format
- checksum notes
- verified mute/unmute packets
- example generated control packets

## Known limitations

- Some treadmills report `steps=0` in notifications; the app falls back to an estimated value based on distance.
- The sound state can initially be unknown until the first relevant notification arrives.
- The UI is intentionally compact and not meant to be a full diagnostic tool.

## Screenshots

- [docs/screenshots/](docs/screenshots/)

## Disclaimer

This project is unofficial and is not affiliated with PitPat. Use it at your own risk.
