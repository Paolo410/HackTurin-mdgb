#!/usr/bin/env bash
# Porta sull'Arduino UNO Q SOLO il codice di comms che gira lì: niente app del PC, test o documentazione.
#
#   ./comms/deploy/push_to_arduino.sh arduino@192.168.1.50               copia, prepara Python (~/venv) e comms/.env
#   ./comms/deploy/push_to_arduino.sh arduino@192.168.1.50 --service     in più avvio automatico (chiede la password)
#   ./comms/deploy/push_to_arduino.sh arduino@192.168.1.50 --tools       in più i 3 strumenti di collaudo (prima prova)
#   ./comms/deploy/push_to_arduino.sh arduino@192.168.1.50 --broker 192.168.1.20    broker su un altro PC
#   ./comms/deploy/push_to_arduino.sh --pack [--tools]                    crea mdgb-nodo.tar.gz da copiare a mano
#
# Il broker (MQTT_HOST in comms/.env) diventa QUESTO PC visto dalla scheda: lancialo dal PC dove gira l'app
# MDGB Centrale (oppure --broker). In modalità cloud (MQTT_TLS=1) comms/.env non viene toccato.
# Sulla scheda: ~/HackTurin-mdgb/comms/{node/ (il programma della rete), actuators.py + jsonl.py (visione <-> MCU,
# li importa ai/), requirements.txt, .env.example, deploy/mdgb-comms.service}; con --tools anche
# tools/{ble_beacon_test,c1_send,c3_sim}.py. Gli eventi di ai/ vanno in ~/HackTurin-mdgb/logs/c3/.
# Rilanciarlo aggiorna il codice: i dati del nodo (comms/node/data) restano.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
FILES=(comms/__init__.py comms/node comms/actuators.py comms/jsonl.py
       comms/requirements.txt comms/.env.example comms/deploy/mdgb-comms.service)
TOOLS=(comms/tools/__init__.py comms/tools/ble_beacon_test.py comms/tools/c1_send.py comms/tools/c3_sim.py)
case " $* " in *" --tools "*) FILES+=("${TOOLS[@]}") ;; esac
pack() {   # tar senza file nascosti di macOS (._*) né cache Python
  (cd "$ROOT" && COPYFILE_DISABLE=1 tar --no-mac-metadata -czf - --exclude='__pycache__' --exclude='*.pyc' \
     --exclude='comms/node/data' "${FILES[@]}")
}

if [ "${1:-}" = "--pack" ]; then
  pack > mdgb-nodo.tar.gz
  echo "Creato mdgb-nodo.tar.gz. Sulla scheda: mkdir -p ~/HackTurin-mdgb && tar -xzf mdgb-nodo.tar.gz -C ~/HackTurin-mdgb"
  echo "poi: python3 -m venv ~/venv && ~/venv/bin/pip install -r ~/HackTurin-mdgb/comms/requirements.txt"
  exit 0
fi
TARGET="${1:?uso: push_to_arduino.sh utente@ip-della-scheda [--service] [--tools] [--broker IP]   oppure   --pack}"
shift
SERVICE=0
BROKER=""
while [ $# -gt 0 ]; do
  case "$1" in
    --service) SERVICE=1 ;;
    --tools) ;;
    --broker) BROKER="${2:?--broker vuole un indirizzo IP}"; shift ;;
    *) echo "opzione sconosciuta: $1"; exit 2 ;;
  esac
  shift
done

echo "1/3 copio il codice della rete su $TARGET:~/HackTurin-mdgb"
pack | ssh "$TARGET" "mkdir -p ~/HackTurin-mdgb && tar -xzf - -C ~/HackTurin-mdgb"

echo "2/3 preparo Python sulla scheda (~/venv, serve Internet la prima volta) e comms/.env"
ssh "$TARGET" "BROKER='$BROKER' bash -s" <<'REMOTE'
set -e
cd ~/HackTurin-mdgb
[ -x ~/venv/bin/python ] || python3 -m venv ~/venv \
  || { echo "Manca python3-venv sulla scheda: sudo apt install python3-venv, poi rilancia"; exit 1; }
~/venv/bin/pip install -q -r comms/requirements.txt
[ -f comms/.env ] || cp comms/.env.example comms/.env
BROKER="${BROKER:-${SSH_CLIENT%% *}}"            # di default: il PC da cui parte questo script
if grep -q '^MQTT_TLS=1' comms/.env; then
  echo "   comms/.env in modalità cloud (MQTT_TLS=1): lasciato com'è"
elif [ -n "$BROKER" ]; then
  sed -i.bak "s/^MQTT_HOST=.*/MQTT_HOST=$BROKER/" comms/.env && rm -f comms/.env.bak
  echo "   broker MQTT = $BROKER:1883 (l'app MDGB Centrale deve essere aperta lì)"
fi
command -v btmgmt >/dev/null || echo "   ATTENZIONE: manca btmgmt, il backup Bluetooth non può partire: sudo apt install bluez"
[ -S /var/run/arduino-router.sock ] || echo "   ATTENZIONE: arduino-router non attivo (serve a ai/ per il semaforo): systemctl status arduino-router"
REMOTE

if [ "$SERVICE" = 1 ]; then
  echo "3/3 avvio automatico (systemd): la scheda chiede la password di sudo"
  ssh -t "$TARGET" 'sed "s#/home/arduino#$HOME#g" ~/HackTurin-mdgb/comms/deploy/mdgb-comms.service \
      | sudo tee /etc/systemd/system/mdgb-comms.service >/dev/null \
    && sudo systemctl daemon-reload && sudo systemctl enable mdgb-comms && sudo systemctl restart mdgb-comms \
    && sleep 3 && sudo journalctl -u mdgb-comms -n 8 --no-pager'
  echo
  echo "Fatto: il nodo gira e ripartirà da solo a ogni accensione. Log: ssh $TARGET 'journalctl -u mdgb-comms -f'"
else
  echo "3/3 (avvio automatico non richiesto: aggiungi --service)"
  echo
  echo "Fatto. Prova a mano sulla scheda:"
  echo "  sudo ~/venv/bin/python ~/HackTurin-mdgb/comms/node/main.py     (nel log: 'backup BLE reale (btmgmt)')"
  echo "Se il servizio era già installato, riavvialo per usare il codice nuovo: sudo systemctl restart mdgb-comms"
fi
