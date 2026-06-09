#!/bin/bash
# create_app.sh — Vytvorí DiskRecovery.app pre macOS
# Spusti: bash create_app.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_NAME="DiskRecovery"
APP_DIR="$SCRIPT_DIR/$APP_NAME.app"
MACOS_DIR="$APP_DIR/Contents/MacOS"
RESOURCES_DIR="$APP_DIR/Contents/Resources"
PYTHON_BIN="$(which python3)"

echo "📦 Vytváram $APP_NAME.app..."

# Vymaž starú verziu
rm -rf "$APP_DIR"

# Vytvor štruktúru .app
mkdir -p "$MACOS_DIR"
mkdir -p "$RESOURCES_DIR"

# ── Info.plist ────────────────────────────────────────────────
cat > "$APP_DIR/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundleDisplayName</key>
  <string>Disk Recovery AI</string>
  <key>CFBundleIdentifier</key>
  <string>com.skuska.diskrecovery</string>
  <key>CFBundleVersion</key>
  <string>1.0</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
  <key>LSUIElement</key>
  <false/>
</dict>
</plist>
EOF

# ── Spustiteľný skript ─────────────────────────────────────────
EXEC_PATH="$MACOS_DIR/$APP_NAME"
cat > "$EXEC_PATH" << BASHEOF
#!/bin/bash
# Disk Recovery AI — macOS launcher

# Pracovný adresár = priečinok kde leží .app
APP_PATH="\$(dirname "\$(dirname "\$(dirname "\$(realpath "\$0")")")")"
PROJECT_DIR="\$(dirname "\$APP_PATH")"

cd "\$PROJECT_DIR" || exit 1

# Načítaj .env
if [ -f ".env" ]; then
  export \$(grep -v '^#' .env | xargs) 2>/dev/null
fi

# Spusti launcher.py
PYTHON="$PYTHON_BIN"

# Ak Python neexistuje, skús štandardné miesta
if [ ! -f "\$PYTHON" ]; then
  for P in /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
    if [ -f "\$P" ]; then PYTHON="\$P"; break; fi
  done
fi

exec "\$PYTHON" "\$PROJECT_DIR/launcher.py"
BASHEOF

chmod +x "$EXEC_PATH"

echo "✅ $APP_NAME.app vytvorený v: $SCRIPT_DIR"
echo ""
echo "Použi: open '$APP_DIR'"
echo "alebo presuň DiskRecovery.app do /Applications"
