#!/usr/bin/env bash
# Porta sull'Arduino UNO Q SOLO il codice della rete (comms): niente app del PC, test, AWS o documentazione.
#
#   ./comms/deploy/push_to_arduino.sh arduino@192.168.1.50     copia via ssh in ~/mdgb e prepara Python (~/venv)
#   ./comms/deploy/push_to_arduino.sh --pack                    crea mdgb-nodo.tar.gz da copiare a mano (chiavetta)
#
# Sulla scheda: ~/mdgb/comms/{node/, tools/c3_sim.py, tools/ble_beacon_test.py, actuators.py, jsonl.py,
# requirements.txt, .env.example, deploy/mdgb-comms.service}. Gli eventi di ai/ vanno in ~/mdgb/logs/c3/.
# Rilanciarlo aggiorna il codice: comms/.env e i dati sulla scheda restano.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FILES=(comms/__init__.py comms/node comms/actuators.py comms/jsonl.py
       comms/tools/__init__.py comms/tools/c3_sim.py comms/tools/ble_beacon_test.py
       comms/requirements.txt comms/.env.example comms/deploy/mdgb-comms.service)
pack() {   # tar senza file nascosti di macOS (._*) né cache Python
  (cd "$ROOT" && COPYFILE_DISABLE=1 tar --no-mac-metadata -czf - --exclude='__pycache__' --exclude='*.pyc' \
     --exclude='comms/node/data' "${FILES[@]}")
}

if [ "${1:-}" = "--pack" ]; then
  pack > mdgb-nodo.tar.gz
  echo "Creato mdgb-nodo.tar.gz. Sulla scheda: mkdir -p ~/mdgb && tar -xzf mdgb-nodo.tar.gz -C ~/mdgb"
  exit 0
fi
TARGET="${1:?uso: push_to_arduino.sh utente@ip-della-scheda   oppure   --pack}"
echo "1/2 copio il codice della rete su $TARGET:~/mdgb"
pack | ssh "$TARGET" "mkdir -p ~/mdgb && tar -xzf - -C ~/mdgb"
echo "2/2 preparo Python sulla scheda (~/venv, serve Internet la prima volta)"
ssh "$TARGET" 'cd ~/mdgb && { [ -x ~/venv/bin/python ] || python3 -m venv ~/venv; } \
  && ~/venv/bin/pip install -q -r comms/requirements.txt \
  && { [ -f comms/.env ] || cp comms/.env.example comms/.env; }'
echo
echo "Fatto. Sulla scheda:"
echo "  nano ~/mdgb/comms/.env                       (MQTT_HOST = indirizzo che l'app sul PC mostra in alto)"
echo "  sudo ~/venv/bin/python ~/mdgb/comms/node/main.py"
