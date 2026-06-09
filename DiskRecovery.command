#!/bin/bash
# DiskRecovery.command
# Dvojklikni na tento súbor — otvorí Terminal a spustí Disk Recovery AI

# Prejdi do priečinka kde leží tento súbor
cd "$(dirname "$0")"

echo "================================================="
echo "  Disk Recovery AI — spúšťam..."
echo "================================================="

# Načítaj API kľúč
if [ -f ".env" ]; then
  export $(grep -v '^#' .env | xargs) 2>/dev/null
fi

# Skontroluj API kľúč
if [ -z "$ANTHROPIC_API_KEY" ]; then
  echo ""
  echo "[CHYBA] ANTHROPIC_API_KEY nie je nastavený v .env súbore!"
  read -p "Stlač Enter pre ukončenie..."
  exit 1
fi

# Nájdi Python
PYTHON=""
for P in \
  /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 \
  /opt/homebrew/bin/python3 \
  /usr/local/bin/python3 \
  /usr/bin/python3; do
  if [ -f "$P" ]; then PYTHON="$P"; break; fi
done

if [ -z "$PYTHON" ]; then
  echo "[CHYBA] Python3 nebol nájdený!"
  read -p "Stlač Enter pre ukončenie..."
  exit 1
fi

echo "  Python:  $PYTHON"
echo "  API key: ${ANTHROPIC_API_KEY:0:12}..."
echo ""
echo "  Spúšťam server... (Safari sa otvorí automaticky)"
echo "  Zatvor toto okno = server sa ukončí"
echo "================================================="
echo ""

exec "$PYTHON" "$(dirname "$0")/launcher.py"
