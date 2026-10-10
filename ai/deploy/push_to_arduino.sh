#!/usr/bin/env bash
# Copies to the Arduino UNO Q ONLY what the vision needs to run there: no tests, no sample videos, no docs.
# Same layout as comms/deploy/push_to_arduino.sh: everything under ~/HackTurin-mdgb on the board, Python in ~/venv.
#
#   ./ai/deploy/push_to_arduino.sh arduino@192.168.1.50                    copy, prepare Python (~/venv)
#   ./ai/deploy/push_to_arduino.sh arduino@192.168.1.50 --applab <folder>  events in the folder of the App Lab app
#        of the sketch (~/ArduinoApps/<folder>/data/c3): the network node reads them there, and the vision
#        reads there the sensors, the shock alarm and the badge written by that app
#   ./ai/deploy/push_to_arduino.sh arduino@192.168.1.50 --service          also start at boot (asks the sudo password)
#   ./ai/deploy/push_to_arduino.sh --pack                                  makes mdgb-ai.tar.gz to copy by hand
#
# On the board: ~/HackTurin-mdgb/ai/{smartcrossing/, config.yaml, calib*.json, models/yolox_nano_dynamic.onnx,
# requirements.txt, scripts/bench.py, deploy/mdgb-ai.service}. Running it again updates the code.
# The semaphore link (--actuator bridge) needs comms/actuators.py on the board: comms/deploy/push_to_arduino.sh.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FILES=(ai/smartcrossing ai/config.yaml ai/calib.example.json ai/calib_thermal.example.json ai/requirements.txt
       ai/scripts/bench.py ai/deploy/mdgb-ai.service ai/models/yolox_nano_dynamic.onnx)
[ -f "$ROOT/ai/calib.json" ] && FILES+=(ai/calib.json)            # the calibration of the mounted camera, if made
[ -f "$ROOT/ai/calib_thermal.json" ] && FILES+=(ai/calib_thermal.json)
[ -f "$ROOT/ai/models/yolox_nano_dynamic.onnx" ] || { echo "Manca il modello: lancia prima ai/scripts/get_model.sh"; exit 1; }
pack() {   # tar without the hidden files of macOS (._*) and without Python caches
  (cd "$ROOT" && COPYFILE_DISABLE=1 tar --no-mac-metadata -czf - --exclude='__pycache__' --exclude='*.pyc' "${FILES[@]}")
}

if [ "${1:-}" = "--pack" ]; then
  pack > mdgb-ai.tar.gz
  echo "Creato mdgb-ai.tar.gz. Sulla scheda: mkdir -p ~/HackTurin-mdgb && tar -xzf mdgb-ai.tar.gz -C ~/HackTurin-mdgb"
  echo "poi: python3 -m venv ~/venv && ~/venv/bin/pip install -r ~/HackTurin-mdgb/ai/requirements.txt"
  exit 0
fi
TARGET="${1:?uso: push_to_arduino.sh utente@ip-della-scheda [--applab CARTELLA] [--service]   oppure   --pack}"
shift
SERVICE=0
APPLAB=""
while [ $# -gt 0 ]; do
  case "$1" in
    --service) SERVICE=1 ;;
    --applab) APPLAB="${2:?--applab vuole il nome della cartella in ~/ArduinoApps}"; shift ;;
    *) echo "opzione sconosciuta: $1"; exit 2 ;;
  esac
  shift
done

echo "1/3 copio la visione su $TARGET:~/HackTurin-mdgb/ai"
pack | ssh "$TARGET" "mkdir -p ~/HackTurin-mdgb && tar -xzf - -C ~/HackTurin-mdgb"

echo "2/3 preparo Python sulla scheda (~/venv, serve Internet la prima volta: circa 500 MB)"
ssh "$TARGET" "APPLAB='$APPLAB' bash -s" <<'REMOTE'
set -e
cd ~/HackTurin-mdgb
[ -x ~/venv/bin/python ] || python3 -m venv ~/venv \
  || { echo "Manca python3-venv sulla scheda: sudo apt install python3-venv, poi rilancia"; exit 1; }
~/venv/bin/pip install -q -r ai/requirements.txt
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
[ -f comms/actuators.py ] || echo "   NOTA: manca comms/actuators.py (lo porta comms/deploy/push_to_arduino.sh): per ora solo --actuator sim"
ls /dev/video* >/dev/null 2>&1 || echo "   ATTENZIONE: nessuna camera in /dev/video*"
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
  echo "Fatto. Prova a mano sulla scheda (ssh $TARGET), con la camera libera:"
  echo '  cd ~/HackTurin-mdgb/ai && ~/venv/bin/python scripts/bench.py 0 --profile unoq'
  echo '  MDGB_C3_DIR=$(cat .c3_dir) ~/venv/bin/python -m smartcrossing.app --source 0 --profile unoq --headless \'
  echo '      --actuator bridge --operator-port 8090'
fi
