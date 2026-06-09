#!/usr/bin/env python3
"""
launcher.py — Disk Recovery AI — natívny macOS launcher

Spustí Flask server na pozadí a otvorí app v Safari.
Dvojklik na DiskRecovery.app → všetko sa spustí automaticky.
"""

import os
import sys
import time
import threading
import subprocess
import urllib.request
from pathlib import Path

# ── Pracovný adresár = root projektu ─────────────────────────
ROOT = Path(__file__).parent.resolve()
os.chdir(ROOT)

# ── Načítaj .env ──────────────────────────────────────────────
env_file = ROOT / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip())

# ── Pridaj disk_recovery do Python path ───────────────────────
sys.path.insert(0, str(ROOT))

PORT = 5001
URL  = f"http://localhost:{PORT}"

# ── Spusti Flask server v background threade ─────────────────
def _start_flask():
    from disk_recovery.ui import app as flask_app
    flask_app.run(
        host="127.0.0.1",
        port=PORT,
        debug=False,
        threaded=True,
        use_reloader=False,
    )

flask_thread = threading.Thread(target=_start_flask, daemon=True)
flask_thread.start()

# ── Počkaj kým Flask naštartuje (max 10s) ────────────────────
for _ in range(20):
    try:
        urllib.request.urlopen(URL, timeout=1)
        break
    except Exception:
        time.sleep(0.5)
else:
    subprocess.run([
        "osascript", "-e",
        'display alert "Disk Recovery AI" message "Flask server sa nespustil." as critical'
    ])
    sys.exit(1)

# ── Otvor v Safari ────────────────────────────────────────────
subprocess.run(["open", "-a", "Safari", URL])

# ── Drž server živý kým je Safari otvorené ───────────────────
# Kontrolujeme každé 2s či Safari stále beží
try:
    while True:
        time.sleep(2)
        result = subprocess.run(
            ["osascript", "-e",
             'tell application "System Events" to (name of processes) contains "Safari"'],
            capture_output=True, text=True,
        )
        # Ak Safari bolo zavreté, ukončíme server
        # (voliteľné — môžeme nechať bežať neobmedzene)
except KeyboardInterrupt:
    pass
