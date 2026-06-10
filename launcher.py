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

# ── Spracovanie signálov pre bezpečné ukončenie ──────────────
def cleanup(signum=None, frame=None):
    print("Ukončujem aplikáciu...")
    # Zastav bežiace orchestrator procesy, ak nejaké sú
    try:
        from disk_recovery.ui import _proc, _sudo_pass
        if _proc and _proc.poll() is None:
            if _sudo_pass:
                subprocess.run(
                    ["sudo", "-S", "pkill", "-9", "-f", "orchestrator.py"],
                    input=f"{_sudo_pass}\n", text=True, capture_output=True
                )
            _proc.kill()
    except Exception:
        pass
    sys.exit(0)

import signal
signal.signal(signal.SIGTERM, cleanup)
signal.signal(signal.SIGINT, cleanup)

# ── Otvor v predvolenom prehliadači (garantované na macOS) ────
subprocess.run(["open", URL])

# ── Drž aplikáciu v Docku, kým ju užívateľ neukončí ─────────
try:
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()  # Skryje hlavné okno, ale nechá aplikáciu v systéme
    
    # Prepojíme príkaz "Quit" z Docku na našu funkciu cleanup
    root.createcommand('::tk::mac::Quit', cleanup)
    
    # Tento loop drží ikonku aplikácie v Docku
    root.mainloop()
except Exception:
    # Ak by tkinter zlyhal, použijeme fallback
    try:
        while True:
            time.sleep(1)
    except BaseException:
        cleanup()
