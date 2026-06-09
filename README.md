# treadmill-tray

A compact Windows tray app for controlling a PitPat treadmill over Bluetooth Low Energy (BLE).

`treadmill-tray` is a practical desktop controller built around the working **FBA BLE protocol path** and verified against real Bluetooth captures. It supports the core treadmill controls, direct speed presets, sound mute/unmute, and a local workout history.

## Features

- Windows tray app with compact controller UI
- BLE device scan and connect
- Start / pause / stop
- Direct speed buttons: **1–6 km/h**
- Fine adjustment: **± 0.1 km/h**
- Verified **sound mute / unmute** support
- Local workout history
- One-file Windows `.exe` build via PyInstaller

## Current UI

Reference screenshot(s) live here:

- [`docs/screenshots/`](docs/screenshots/)
- BLE reverse-engineering reference: [`docs/screenshots/ble-capture-reference.png`](docs/screenshots/ble-capture-reference.png)

> Tip: add fresh app screenshots here before publishing the repo publicly.

## Protocol / HEX commands

A documented overview of the currently known BLE service UUIDs and command packets is available here:

- [`docs/reference/hex-commands.md`](docs/reference/hex-commands.md)

## Project structure

```text
tray_app.py              Main Windows tray UI
bluetooth_manager_fba.py BLE connection / notifications / writes
treadmill_controller.py  Packet generation for treadmill commands
treadmill_data.py        Payload parsing / telemetry decoding
workout_history.py       Local persistent workout history
__main__.py              Alternate Python entry point
build-release.sh         Helper script for PyInstaller builds
docs/
  reference/
    hex-commands.md
  screenshots/
```

## Requirements

- Windows
- Python 3.14+ (tested locally with Python 3.14)
- Bluetooth adapter with BLE support

Python packages:

- `bleak`
- `pystray`
- `Pillow`
- `pyinstaller` (for release builds)

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

## Run locally

```bash
python tray_app.py
```

or:

```bash
python __main__.py
```

## Build a Windows release

Quick build:

```bash
bash build-release.sh
```

Or manually:

```bash
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --clean --onefile --windowed --name treadmill-tray tray_app.py
```

Expected output:

- `dist/treadmill-tray.exe`

## Workout history

Workout history is stored locally in:

- `%APPDATA%/treadmill-tray/workout_history.json`

Each entry stores, where available:

- start time
- duration
- distance
- steps
- calories
- average speed
- target speed

## Known limitations

- Some treadmills appear to report `steps=0` in BLE notifications; the app falls back to an estimated step count based on distance.
- The sound state may initially be unknown until the first relevant notification arrives.
- The UI is optimized for practical use, not for exhaustive device diagnostics.

## Development notes

- The active BLE path is the **FBA** service/characteristic family.
- Sound mute/unmute commands were verified against a real Bluetooth capture.
- Legacy / unused artifacts were intentionally removed to keep the repo cleaner.

## Support the project

If this project saved you time or helped you get your treadmill working, you can support it with a coffee or a beer:

- **Ko-fi:** [☕ Buy me a coffee on Ko-fi](https://ko-fi.com/heilmic)


## Disclaimer

This project is unofficial and is not affiliated with PitPat. Use it at your own risk.
