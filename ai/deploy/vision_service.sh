#!/usr/bin/env bash
# What the mdgb-ai service runs: the vision on the camera or, for tests and benchmarks, on a recorded video as if it
# came from the camera. The source and its options are in ai/.vision_args (one line, written by
# `run_vision.sh video ...`); without that file, the camera. Changing it needs no sudo: run_vision.sh restarts the
# process and systemd starts it again.
set -euo pipefail
AI="$(cd "$(dirname "$0")/.." && pwd)"
cd "$AI"
ARGS="--source 0"
if [ -s .vision_args ]; then ARGS="$(cat .vision_args)"; fi
echo "vision source: $ARGS"
# libcamerify: the camera of the board is a CSI sensor read by libcamera (harmless with a video file).
# $ARGS unquoted on purpose: it holds several options.
exec /usr/bin/libcamerify "${HOME:-/home/arduino}/venv/bin/python" -u -m smartcrossing.app --profile unoq --headless \
    --actuator bridge --operator-port 8090 $ARGS
