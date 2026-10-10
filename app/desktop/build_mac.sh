#!/usr/bin/env bash
# Crea "MDGB Centrale.app" in app/desktop/dist/ (macOS). Una volta sola, ~2 minuti:
#   ./app/desktop/build_mac.sh
# Poi trascina l'app in Applicazioni e aprila con doppio clic.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="$HERE/build"
mkdir -p "$BUILD"

echo "1/3 ambiente di build (app/desktop/build/venv)"
[ -x "$BUILD/venv/bin/python" ] || python3 -m venv "$BUILD/venv"
"$BUILD/venv/bin/pip" install -q --upgrade pip
"$BUILD/venv/bin/pip" install -q -r "$HERE/requirements.txt"

echo "2/3 icona"
"$BUILD/venv/bin/python" "$HERE/make_icon.py" "$BUILD/icon.png"
rm -rf "$BUILD/icon.iconset" && mkdir "$BUILD/icon.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s "$BUILD/icon.png" --out "$BUILD/icon.iconset/icon_${s}x${s}.png" >/dev/null
  sips -z $((s * 2)) $((s * 2)) "$BUILD/icon.png" --out "$BUILD/icon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$BUILD/icon.iconset" -o "$BUILD/icon.icns"

echo "3/3 app"
"$BUILD/venv/bin/pyinstaller" --noconfirm --clean --log-level WARN \
  --distpath "$HERE/dist" --workpath "$BUILD/pyinstaller" "$HERE/centrale.spec"

echo
echo "Pronta: $HERE/dist/MDGB Centrale.app"
echo "Trascinala in Applicazioni (o apri la cartella con: open \"$HERE/dist\") e fai doppio clic."
