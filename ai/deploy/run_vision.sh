#!/usr/bin/env bash
# Starts and stops the vision on the board by hand, in the background (no sudo needed, unlike the service).
#   ~/HackTurin-mdgb/ai/deploy/run_vision.sh start [more options of smartcrossing.app]
#   ~/HackTurin-mdgb/ai/deploy/run_vision.sh stop | status | log
# With the vision installed as a service (mdgb-ai), no sudo needed either:
#   run_vision.sh video samples/Torino_1.mp4 --calib samples/calib/torino_1.json   a recorded video, in a loop, as if it
#                                         came from the camera: same commands to the traffic light, page, events
#   run_vision.sh video samples/X.mp4 --once     one pass, then the table of the times (and again, systemd restarts it)
#   run_vision.sh camera                  back to the camera
#   run_vision.sh record 60 [name]        records a clip from the camera into samples/clips/ (benchmark, checks):
#                                         only while the vision is on a video, because the camera has one reader
#   run_vision.sh restart                 restart the service (after a code update)
# Log in ~/HackTurin-mdgb/logs/vision.log. The technician's page is on port 8090.
set -euo pipefail
AI="$(cd "$(dirname "$0")/.." && pwd)"
LOGS="$AI/../logs"
LOG="$LOGS/vision.log"
PIDFILE="$LOGS/vision.pid"
running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

service_on() { systemctl is-active --quiet mdgb-ai 2>/dev/null; }

# The service runs as this user: Ctrl+C to its process, and systemd starts it again with the new source.
restart_service() {
  local old new
  old="$(systemctl show mdgb-ai -p MainPID --value)"
  [ "$old" != 0 ] && kill -INT "$old"
  for _ in $(seq 1 60); do
    new="$(systemctl show mdgb-ai -p MainPID --value)"
    if [ "$new" != 0 ] && [ "$new" != "$old" ]; then echo "Visione riavviata (pid $new). Log: journalctl -u mdgb-ai -f"; return 0; fi
    sleep 0.5
  done
  echo "La visione non è ripartita: journalctl -u mdgb-ai -n 30"; return 1
}
need_service() {
  service_on || { echo "Serve la visione installata come servizio (mdgb-ai): sudo sh ~/mdgb-tools/installa_servizio_visione.sh"; exit 1; }
}

case "${1:-status}" in
  start)
    if running; then echo "La visione è già accesa (pid $(cat "$PIDFILE"))."; exit 0; fi
    # Installed as a service it starts by itself: a second copy could not open the camera.
    if service_on; then echo "La visione gira già come servizio (mdgb-ai): sudo systemctl restart mdgb-ai"; exit 0; fi
    mkdir -p "$LOGS"
    cd "$AI"
    C3="$(cat .c3_dir 2>/dev/null || echo "$LOGS/c3")"
    export LIBCAMERA_IPA_CONFIG_PATH="$AI/deploy/camera_tuning"   # camera without the automatic exposure
    "$HOME/venv/bin/python" scripts/camera_exposure.py || true    # exposure and gain for the light of this moment
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
    elif service_on; then echo "Visione accesa come servizio (mdgb-ai), sorgente: $(cat "$AI/.vision_args" 2>/dev/null || echo camera). Log: journalctl -u mdgb-ai -n 20"
    else echo "Visione spenta."; fi
    ;;
  log)
    if service_on; then journalctl -u mdgb-ai -f; else tail -f "$LOG"; fi
    ;;
  record)
    cd "$AI"
    if service_on && [ ! -s .vision_args ]; then
      echo "La camera è occupata dalla visione. Prima: run_vision.sh video samples/<video>.mp4   Alla fine: run_vision.sh camera"; exit 1
    fi
    if running; then echo "La camera è occupata dalla visione accesa a mano: run_vision.sh stop"; exit 1; fi
    export LIBCAMERA_IPA_CONFIG_PATH="$AI/deploy/camera_tuning"
    "$HOME/venv/bin/python" scripts/camera_exposure.py || true
    NAME=()
    [ -n "${3:-}" ] && NAME=(--name "$3")
    libcamerify "$HOME/venv/bin/python" scripts/record_clip.py --seconds "${2:-30}" "${NAME[@]}" 2>&1 | grep -v " WARN \| INFO "
    ;;
  video)
    need_service
    [ -n "${2:-}" ] || { echo "uso: run_vision.sh video <file video> [--calib <calib.json>] [--once] [altre opzioni]"; exit 2; }
    cd "$AI"
    [ -f "$2" ] || { echo "Video non trovato: $2 (percorso da ~/HackTurin-mdgb/ai)"; exit 1; }
    VIDEO="$(cd "$(dirname "$2")" && pwd)/$(basename "$2")"
    LOOP="--loop"
    EXTRA=()
    for a in "${@:3}"; do if [ "$a" = "--once" ]; then LOOP=""; else EXTRA+=("$a"); fi; done
    echo "--source $VIDEO $LOOP ${EXTRA[*]:-}" > .vision_args
    echo "Visione sul video $VIDEO ${LOOP:+(in loop)}: semaforo, pagina del tecnico ed eventi come con la camera."
    restart_service
    ;;
  camera)
    need_service
    rm -f "$AI/.vision_args"
    echo "Visione sulla camera."
    restart_service
    ;;
  restart)
    need_service
    restart_service
    ;;
  *)
    echo "uso: run_vision.sh start|stop|status|log|video|camera|record|restart"; exit 2
    ;;
esac
