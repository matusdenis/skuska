#!/usr/bin/env python3
"""
launcher.py — Disk Recovery AI — natívny macOS launcher

Spustí Flask server na pozadí a otvorí natívne macOS okno (WKWebView).
Dvojklik na DiskRecovery.app → všetko sa spustí automaticky.
"""

import os
import sys
import time
import threading
import urllib.request
from pathlib import Path

# ── Nastav pracovný adresár na root projektu ──────────────────
ROOT = Path(__file__).parent
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
    from disk_recovery.ui import app
    app.run(host="127.0.0.1", port=PORT, debug=False, threaded=True, use_reloader=False)

flask_thread = threading.Thread(target=_start_flask, daemon=True)
flask_thread.start()

# ── Počkaj kým Flask naštartuje (max 10s) ────────────────────
print("Štartujem Disk Recovery AI...")
for _ in range(20):
    try:
        urllib.request.urlopen(URL, timeout=1)
        break
    except Exception:
        time.sleep(0.5)
else:
    print(f"[CHYBA] Flask server sa nespustil na {URL}")
    sys.exit(1)

print(f"Server beží na {URL}")

# ── Otvor natívne macOS okno ─────────────────────────────────
try:
    import webview

    window = webview.create_window(
        title="Disk Recovery AI",
        url=URL,
        width=1280,
        height=820,
        min_size=(900, 600),
        background_color="#0f1117",
    )

    webview.start(debug=False)

except ImportError:
    # Fallback: otvor v prehliadači ak pywebview nie je k dispozícii
    import subprocess
    print("pywebview nie je nainštalovaný — otváram v prehliadači...")
    subprocess.Popen(["open", URL])
    # Drž server živý
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
