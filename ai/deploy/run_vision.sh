#!/usr/bin/env bash
# Starts and stops the vision on the board by hand, in the background (no sudo needed, unlike the service).
#   ~/HackTurin-mdgb/ai/deploy/run_vision.sh start [more options of smartcrossing.app]
#   ~/HackTurin-mdgb/ai/deploy/run_vision.sh stop | status | log
# Log in ~/HackTurin-mdgb/logs/vision.log. The technician's page is on port 8090.
set -euo pipefail
AI="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$AI/../logs"
LOG="$LOGS/vision.log"
PIDFILE="$LOGS/vision.pid"
running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

service_on() { systemctl is-active --quiet mdgb-ai 2>/dev/null; }

case "${1:-status}" in
  start)
    if running; then echo "La visione è già accesa (pid $(cat "$PIDFILE"))."; exit 0; fi
    # Installed as a service it starts by itself: a second copy could not open the camera.
    if service_on; then echo "La visione gira già come servizio (mdgb-ai): sudo systemctl restart mdgb-ai"; exit 0; fi
    mkdir -p "$LOGS"
    cd "$AI"
    C3="$(cat .c3_dir 2>/dev/null || echo "$LOGS/c3")"
    # libcamerify: the camera of the board is a CSI sensor read by libcamera. -u: the log is written at once.
    MDGB_C3_DIR="$C3" nohup libcamerify "$HOME/venv/bin/python" -u -m smartcrossing.app --source 0 --profile unoq \
        --headless --actuator bridge --operator-port 8090 "${@:2}" >> "$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 6
    if running; then echo "Visione accesa (pid $(cat "$PIDFILE")). Log: $LOG"; else echo "La visione non è partita:"; tail -15 "$LOG"; exit 1; fi
    ;;
  stop)
    if running; then
      kill -INT "$(cat "$PIDFILE")"                     # like Ctrl+C: closes the camera and the link cleanly
      for _ in $(seq 1 20); do running || break; sleep 0.5; done
      running && kill "$(cat "$PIDFILE")"
      echo "Visione spenta: il semaforo torna al ciclo normale."
    else
      echo "La visione non era accesa."
    fi
    rm -f "$PIDFILE"
    ;;
  status)
    if running; then echo "Visione accesa (pid $(cat "$PIDFILE"))."; grep -a "state=" "$LOG" | tail -2
    elif service_on; then echo "Visione accesa come servizio (mdgb-ai). Log: journalctl -u mdgb-ai -n 20"
    else echo "Visione spenta."; fi
    ;;
  log)
    tail -f "$LOG"
    ;;
  *)
    echo "uso: run_vision.sh start|stop|status|log"; exit 2
    ;;
esac
