#!/bin/bash
# create_app.sh — Vytvorí DiskRecovery.app pre macOS
# Spusti: bash create_app.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="DiskRecovery"
APP_DIR="$SCRIPT_DIR/$APP_NAME.app"
MACOS_DIR="$APP_DIR/Contents/MacOS"
PYTHON_BIN="$(which python3)"

echo "Vytváram $APP_NAME.app..."

rm -rf "$APP_DIR"
mkdir -p "$MACOS_DIR"
mkdir -p "$APP_DIR/Contents/Resources"

# Zapíš Python cestu a projekt do Resources
echo "$PYTHON_BIN" > "$APP_DIR/Contents/Resources/python_path.txt"
echo "$SCRIPT_DIR"  > "$APP_DIR/Contents/Resources/project_dir.txt"

# Info.plist
cat > "$APP_DIR/Contents/Info.plist" << PLISTEOF
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
PLISTEOF

# Spustiteľný skript — zapisujeme cez python aby sa vyhlo problémom s heredoc escaping
python3 - << PYEOF
import os, stat

script = r"""#!/bin/bash
RESOURCES="$(cd "$(dirname "$0")/../Resources" && pwd)"
PYTHON_BIN="$(cat "$RESOURCES/python_path.txt")"
PROJECT_DIR="$(cat "$RESOURCES/project_dir.txt")"

[ -f "$PYTHON_BIN" ] || PYTHON_BIN="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
[ -f "$PYTHON_BIN" ] || PYTHON_BIN="/opt/homebrew/bin/python3"
[ -f "$PYTHON_BIN" ] || PYTHON_BIN="$(which python3)"

cd "$PROJECT_DIR" || exit 1

if [ -f ".env" ]; then
  set -a
  source .env
  set +a
fi

exec "$PYTHON_BIN" "$PROJECT_DIR/launcher.py"
"""

path = "$MACOS_DIR/$APP_NAME"
with open(path, "w") as f:
    f.write(script)
os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
print("  Skript zapísaný.")
PYEOF

# Odstráň quarantine (Gatekeeper)
xattr -cr "$APP_DIR" 2>/dev/null || true

echo ""
echo "✅ $APP_NAME.app je v: $SCRIPT_DIR"
echo "   Dvojklikni na DiskRecovery.app"
echo "   Ak macOS zablokuje: Pravý klik → Otvoriť"
