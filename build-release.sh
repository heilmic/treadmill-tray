#!/usr/bin/env bash
set -euo pipefail

python -m pip install pyinstaller
pyinstaller --noconfirm --clean --onefile --windowed --name treadmill-tray tray_app.py
