#!/usr/bin/env bash
# Copies to the Arduino UNO Q ONLY what the vision needs to run there: no tests, no sample videos, no docs.
# Same layout as comms/deploy/push_to_arduino.sh: everything under ~/HackTurin-mdgb on the board, Python in ~/venv.
#
#   ./ai/deploy/push_to_arduino.sh arduino@192.168.1.50                    copy, prepare Python (~/venv)
#   ./ai/deploy/push_to_arduino.sh arduino@192.168.1.50 --bridge           also what is needed to command the
#        traffic light (--actuator bridge): the three files of comms/ that talk to the sketch, taken from the
#        working tree or, until they are on main, from the git ref in MDGB_COMMS_REF (default
#        origin/lorenzo/ble-backup), and the arduino-router-bridge package. Not the network node.
#   ./ai/deploy/push_to_arduino.sh arduino@192.168.1.50 --applab <folder>  events in the folder of the App Lab app
#        of the sketch (~/ArduinoApps/<folder>/data/c3): the network node reads them there, and the vision
#        reads there the sensors, the shock alarm and the badge written by that app
#   ./ai/deploy/push_to_arduino.sh arduino@192.168.1.50 --service          also start at boot (asks the sudo password)
#   ./ai/deploy/push_to_arduino.sh --pack                                  makes mdgb-ai.tar.gz to copy by hand
#
# On the board: ~/HackTurin-mdgb/ai/{smartcrossing/, config.yaml, calib*.json, models/yolox_nano_dynamic.onnx,
# requirements.txt, scripts/{bench,operator_login}.py, deploy/mdgb-ai.service}. Running it again updates the code.
# The technician's credentials (ai/.env) are made on the board with scripts/operator_login.py and never copied.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMMS_REF="${MDGB_COMMS_REF:-origin/lorenzo/ble-backup}"
COMMS_FILES=(comms/__init__.py comms/actuators.py comms/jsonl.py)   # vision <-> sketch over the Bridge (owner: comms)
BRIDGE_PACKAGE="arduino-router-bridge==0.5.1"                       # same pin as comms/requirements.txt
case " $* " in *" --bridge "*) BRIDGE=1 ;; *) BRIDGE=0 ;; esac
FILES=(ai/smartcrossing ai/config.yaml ai/calib.example.json ai/calib_thermal.example.json ai/requirements.txt
       ai/scripts/bench.py ai/scripts/record_clip.py ai/scripts/camera_exposure.py ai/scripts/operator_login.py
       ai/deploy/camera_tuning ai/deploy/mdgb-ai.service ai/deploy/run_vision.sh
       ai/deploy/vision_service.sh ai/models/yolox_nano_dynamic.onnx)
[ -f "$ROOT/ai/calib.json" ] && FILES+=(ai/calib.json)            # the calibration of the mounted camera, if made
[ -f "$ROOT/ai/calib_thermal.json" ] && FILES+=(ai/calib_thermal.json)
[ -f "$ROOT/ai/models/yolox_nano_dynamic.onnx" ] || { echo "Manca il modello: lancia prima ai/scripts/get_model.sh"; exit 1; }
pack() {   # tar without the hidden files of macOS (._*) and without Python caches
  local stage
  stage="$(mktemp -d)"
  (cd "$ROOT" && tar -cf - --exclude='__pycache__' --exclude='*.pyc' "${FILES[@]}") | tar -xf - -C "$stage"
  if [ "$BRIDGE" = 1 ]; then
    if [ -f "$ROOT/comms/actuators.py" ]; then
      (cd "$ROOT" && tar -cf - "${COMMS_FILES[@]}") | tar -xf - -C "$stage"
    else
      (cd "$ROOT" && git archive "$COMMS_REF" "${COMMS_FILES[@]}") | tar -xf - -C "$stage" \
        || { echo "comms/actuators.py non c'è nel repo né in $COMMS_REF (git fetch origin?)" >&2; rm -rf "$stage"; return 1; }
    fi
  fi
  (cd "$stage" && COPYFILE_DISABLE=1 tar --no-mac-metadata --no-xattrs -czf - *)
  rm -rf "$stage"
}

if [ "${1:-}" = "--pack" ]; then
  pack > mdgb-ai.tar.gz
  echo "Creato mdgb-ai.tar.gz. Sulla scheda: mkdir -p ~/HackTurin-mdgb && tar -xzf mdgb-ai.tar.gz -C ~/HackTurin-mdgb"
  echo "poi: python3 -m venv ~/venv && ~/venv/bin/pip install -r ~/HackTurin-mdgb/ai/requirements.txt"
  exit 0
fi
TARGET="${1:?uso: push_to_arduino.sh utente@ip-della-scheda [--bridge] [--applab CARTELLA] [--service]   oppure   --pack}"
shift
SERVICE=0
APPLAB=""
while [ $# -gt 0 ]; do
  case "$1" in
    --service) SERVICE=1 ;;
    --bridge) ;;
    --applab) APPLAB="${2:?--applab vuole il nome della cartella in ~/ArduinoApps}"; shift ;;
    *) echo "opzione sconosciuta: $1"; exit 2 ;;
  esac
  shift
done

echo "1/3 copio la visione su $TARGET:~/HackTurin-mdgb/ai"
pack | ssh "$TARGET" "mkdir -p ~/HackTurin-mdgb && tar -xzf - -C ~/HackTurin-mdgb"

echo "2/3 preparo Python sulla scheda (~/venv, serve Internet la prima volta: circa 500 MB)"
ssh "$TARGET" "APPLAB='$APPLAB' BRIDGE='$BRIDGE' BRIDGE_PACKAGE='$BRIDGE_PACKAGE' bash -s" <<'REMOTE'
set -e
cd ~/HackTurin-mdgb
# The board image has pip but not python3-venv (it needs sudo): then the environment is made without its
# own pip and the pip of the system installs into it. Nothing is installed outside ~/venv.
if [ ! -x ~/venv/bin/python ]; then
  python3 -m venv ~/venv 2>/dev/null || { rm -rf ~/venv; python3 -m venv --without-pip ~/venv; }
fi
if ~/venv/bin/python -m pip --version >/dev/null 2>&1; then
  venv_pip() { ~/venv/bin/python -m pip "$@"; }
else
  python3 -m pip --version >/dev/null 2>&1 \
    || { echo "Sulla scheda mancano python3-venv e pip: sudo apt install python3-venv, poi rilancia"; exit 1; }
  venv_pip() { python3 -m pip --python ~/venv/bin/python "$@"; }
fi
venv_pip install -q -r ai/requirements.txt
[ "$BRIDGE" = 1 ] && venv_pip install -q "$BRIDGE_PACKAGE"
# Where the events go: the folder of the App Lab app when there is one, else ~/HackTurin-mdgb/logs/c3.
C3_DIR="$HOME/HackTurin-mdgb/logs/c3"
if [ -n "$APPLAB" ]; then
  [ -d ~/ArduinoApps/"$APPLAB" ] || echo "   ATTENZIONE: ~/ArduinoApps/$APPLAB non esiste (ls ~/ArduinoApps)"
  C3_DIR="$HOME/ArduinoApps/$APPLAB/data/c3"
fi
mkdir -p "$C3_DIR" 2>/dev/null || echo "   ATTENZIONE: non posso creare $C3_DIR (permessi della cartella dell'app)"
[ -w "$C3_DIR" ] || echo "   ATTENZIONE: $C3_DIR non è scrivibile da $USER: la visione non potrà salvare gli eventi lì"
echo "$C3_DIR" > ai/.c3_dir
echo "   eventi in $C3_DIR"
[ -f ai/calib.json ] || echo "   NOTA: manca ai/calib.json (camera non calibrata): si contano i passaggi, niente velocità né regole"
[ -f comms/actuators.py ] || echo "   NOTA: manca comms/actuators.py: per comandare il semaforo rilancia con --bridge (per ora solo --actuator sim)"
[ -f ai/.env ] || echo "   NOTA: credenziali del tecnico non impostate: sulla scheda, cd ~/HackTurin-mdgb/ai && ~/venv/bin/python scripts/operator_login.py"
# The camera of the board is a CSI sensor seen by libcamera (a USB webcam would be a plain /dev/video*).
if command -v cam >/dev/null; then
  timeout 10 cam -l 2>/dev/null | grep -q "^[0-9]*:" || echo "   ATTENZIONE: libcamera non vede nessuna camera (cam -l)"
  command -v libcamerify >/dev/null || echo "   ATTENZIONE: manca libcamerify (pacchetto libcamera-v4l2): OpenCV non può aprire la camera CSI"
fi
[ -S /var/run/arduino-router.sock ] || echo "   ATTENZIONE: arduino-router non attivo (serve per comandare il semaforo)"
[ -r /var/run/arduino-router.sock ] && [ -w /var/run/arduino-router.sock ] \
  || echo "   ATTENZIONE: $USER non può usare /var/run/arduino-router.sock: ls -l /var/run/arduino-router.sock"
~/venv/bin/python - <<'PY'
import platform, sys
import cv2, numpy, onnxruntime, supervision, yaml
print(f"   Python {platform.python_version()} {platform.machine()}: numpy {numpy.__version__}, onnxruntime "
      f"{onnxruntime.__version__}, opencv {cv2.__version__}, supervision {supervision.__version__}")
PY
REMOTE

if [ "$SERVICE" = 1 ]; then
  echo "3/3 avvio automatico (systemd): la scheda chiede la password di sudo"
  ssh -t "$TARGET" 'sed -e "s#/home/arduino#$HOME#g" -e "s#^Environment=MDGB_C3_DIR=.*#Environment=MDGB_C3_DIR=$(cat ~/HackTurin-mdgb/ai/.c3_dir)#" \
        ~/HackTurin-mdgb/ai/deploy/mdgb-ai.service | sudo tee /etc/systemd/system/mdgb-ai.service >/dev/null \
    && sudo systemctl daemon-reload && sudo systemctl enable mdgb-ai && sudo systemctl restart mdgb-ai \
    && sleep 5 && sudo journalctl -u mdgb-ai -n 12 --no-pager'
  echo
  echo "Fatto: la visione gira e ripartirà da sola. Log: ssh $TARGET 'journalctl -u mdgb-ai -f'"
else
  echo "3/3 (avvio automatico non richiesto: aggiungi --service quando la prova a mano funziona)"
  echo
  echo "Fatto. Per accendere e spegnere la visione sulla scheda:  ssh $TARGET '~/HackTurin-mdgb/ai/deploy/run_vision.sh start'   (stop, status, log)"
  echo "Oppure a mano (ssh $TARGET), con la camera libera (libcamerify: camera CSI):"
  echo '  cd ~/HackTurin-mdgb/ai && libcamerify ~/venv/bin/python scripts/bench.py 0 --profile unoq'
  echo '  MDGB_C3_DIR=$(cat .c3_dir) libcamerify ~/venv/bin/python -m smartcrossing.app --source 0 --profile unoq \'
  echo '      --headless --actuator bridge --operator-port 8090'
fi
