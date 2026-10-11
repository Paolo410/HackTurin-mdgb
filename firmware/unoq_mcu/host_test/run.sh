#!/usr/bin/env bash
# Logic of the sketch on a PC (no board): firmware/unoq_mcu/host_test/run.sh   -> "all checks passed".
# The sketch is compiled in a temporary folder with a FAKE badge, so the real arduino_secrets.h is never used here.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
cp "$HERE/../sketch/sketch.ino" "$TMP/"
echo '#define SECRET_TECH_BADGE "TEST00000001"' > "$TMP/arduino_secrets.h"
"${CXX:-c++}" -std=c++17 -I "$HERE/fake" -I "$TMP" -include "$TMP/arduino_secrets.h" -o "$TMP/host_test" "$HERE/host_test.cpp"
"$TMP/host_test"
