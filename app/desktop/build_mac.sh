#!/usr/bin/env bash
# Crea "MDGB Centrale.app" in app/desktop/dist/ (macOS). Una volta sola, ~2 minuti:
#   ./app/desktop/build_mac.sh
# Poi trascina l'app in Applicazioni e aprila con doppio clic.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BUILD="$HERE/build"
# l'app si costruisce e si firma fuori dal repo: se il repo è su Desktop/Documenti sincronizzati con iCloud,
# iCloud aggiunge attributi che codesign rifiuta ("resource fork, Finder information... not allowed")
OUT="${TMPDIR:-/tmp}/mdgb-centrale-dist"
mkdir -p "$BUILD"

echo "0/3 broker MQTT locale (Mosquitto)"
if ! command -v mosquitto >/dev/null && [ ! -x /opt/homebrew/sbin/mosquitto ] && [ ! -x /usr/local/sbin/mosquitto ]; then
  command -v brew >/dev/null || { echo "Serve Homebrew (https://brew.sh) per installare Mosquitto"; exit 1; }
  brew install mosquitto
fi

echo "1/3 ambiente di build (app/desktop/build/venv)"
[ -x "$BUILD/venv/bin/python" ] || python3 -m venv "$BUILD/venv"
"$BUILD/venv/bin/pip" install -q --upgrade pip
"$BUILD/venv/bin/pip" install -q -r "$HERE/requirements.txt"

echo "2/3 icona"
# Each size is drawn on its own (the small ones without the name, which would not be readable).
rm -rf "$BUILD/icon.iconset"
"$BUILD/venv/bin/python" "$HERE/make_icon.py" --iconset "$BUILD/icon.iconset"
iconutil -c icns "$BUILD/icon.iconset" -o "$BUILD/icon.icns"

echo "3/3 app"
rm -rf "$OUT"
"$BUILD/venv/bin/pyinstaller" --noconfirm --clean --log-level ERROR \
  --distpath "$OUT" --workpath "$BUILD/pyinstaller" "$HERE/centrale.spec"

# firma ad-hoc dell'intera app (senza, su un altro Mac risulterebbe "danneggiata")
xattr -cr "$OUT/MDGB Centrale.app"
codesign --force --deep --sign - "$OUT/MDGB Centrale.app"
codesign --verify --deep --strict "$OUT/MDGB Centrale.app"

# autotest: l'app appena costruita avvia il suo Mosquitto, la centrale e la dashboard, li controlla ed esce
"$OUT/MDGB Centrale.app/Contents/MacOS/MDGB Centrale" --selftest >/dev/null 2>&1 \
  || { echo "Autotest fallito: vedi centrale.log in ${TMPDIR:-/tmp}/mdgb-selftest-*"; exit 1; }
echo "autotest ok"

# pacchetto per il centralino: solo l'app, zippata (si manda via AirDrop, chiavetta, mail...)
ditto -c -k --keepParent "$OUT/MDGB Centrale.app" "$OUT/MDGB-Centrale-mac.zip"
rm -rf "$HERE/dist" && mkdir -p "$HERE/dist"
ditto "$OUT/MDGB Centrale.app" "$HERE/dist/MDGB Centrale.app"
cp "$OUT/MDGB-Centrale-mac.zip" "$HERE/dist/"

echo
echo "Pronta: $HERE/dist/MDGB Centrale.app"
echo "Per il centralino: $HERE/dist/MDGB-Centrale-mac.zip (contiene solo l'app, Mosquitto incluso)"
echo "Trascinala in Applicazioni (o apri la cartella con: open \"$HERE/dist\") e fai doppio clic."
