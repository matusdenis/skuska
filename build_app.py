#!/usr/bin/env python3
"""
build_app.py — Vytvorí DiskRecovery.app pre macOS
Spusti: python3 build_app.py
"""

import os
import stat
import shutil
import subprocess
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.resolve()
APP_DIR     = PROJECT_DIR / "DiskRecovery.app"
MACOS_DIR   = APP_DIR / "Contents" / "MacOS"
RES_DIR     = APP_DIR / "Contents" / "Resources"
PYTHON_BIN  = subprocess.check_output(["which", "python3"]).decode().strip()

print(f"Vytváram DiskRecovery.app...")
print(f"  Python:  {PYTHON_BIN}")
print(f"  Projekt: {PROJECT_DIR}")

# Vymaž starú verziu
if APP_DIR.exists():
    shutil.rmtree(APP_DIR)

MACOS_DIR.mkdir(parents=True)
RES_DIR.mkdir(parents=True)

# Ulož Python cestu a projekt do Resources
(RES_DIR / "python_path.txt").write_text(PYTHON_BIN + "\n")
(RES_DIR / "project_dir.txt").write_text(str(PROJECT_DIR) + "\n")

# Info.plist
(APP_DIR / "Contents" / "Info.plist").write_text("""\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>DiskRecovery</string>
  <key>CFBundleDisplayName</key><string>Disk Recovery AI</string>
  <key>CFBundleIdentifier</key><string>com.skuska.diskrecovery</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>DiskRecovery</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
""")

# Spustiteľný shell skript — všetky $ sú literálne (raw string)
launcher_sh = r"""#!/bin/bash
MYDIR="$(cd "$(dirname "$0")" && pwd)"
RESOURCES="$MYDIR/../Resources"

PYTHON_BIN="$(cat "$RESOURCES/python_path.txt" 2>/dev/null | tr -d '\n')"
PROJECT_DIR="$(cat "$RESOURCES/project_dir.txt" 2>/dev/null | tr -d '\n')"

# Fallback Python
for P in "$PYTHON_BIN" \
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
  /opt/homebrew/bin/python3 /usr/local/bin/python3 /usr/bin/python3; do
  [ -f "$P" ] && { PYTHON_BIN="$P"; break; }
done

cd "$PROJECT_DIR" || exit 1

# Načítaj .env
if [ -f ".env" ]; then
  while IFS='=' read -r key val; do
    [[ "$key" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${key// }" ]] && continue
    export "$key"="$val"
  done < .env
fi

exec "$PYTHON_BIN" "$PROJECT_DIR/launcher.py"
"""

exec_path = MACOS_DIR / "DiskRecovery"
exec_path.write_text(launcher_sh)
exec_path.chmod(exec_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

# Odstráň quarantine (Gatekeeper)
subprocess.run(["xattr", "-cr", str(APP_DIR)], capture_output=True)

print()
print(f"✅ DiskRecovery.app vytvorený!")
print(f"   Miesto: {APP_DIR}")
print()
print("   Dvojklikni na DiskRecovery.app pre spustenie.")
print("   Ak macOS zablokuje: Pravý klik → Otvoriť → Otvoriť")
