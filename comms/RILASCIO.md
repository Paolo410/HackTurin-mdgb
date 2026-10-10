# Rilascio della rete MDGB: Arduino UNO Q + PC della centrale

## Cosa va dove

```
 ARDUINO UNO Q (sul semaforo)                                   TUO PC (la centrale)
 ┌────────────────────────────────────────┐                    ┌──────────────────────────────────┐
 │ ai/ di Paolo ─► logs/c3/*.jsonl         │                    │ app/central.py  (UNICO programma)│
 │                    │                    │   Wi-Fi + Internet │   ├─ riceve via MQTT da AWS      │
 │ comms/node/main.py ◄┘                   │ ──► AWS IoT Core ──►│   ├─ riceve via Bluetooth (BLE)  │
 │   salva su disco, manda via MQTT        │                    │   ├─ database app/central.db     │
 │   se MQTT tace 30 s: beacon BLE ─────────── radio, ~10–50 m ─►│   └─ diagnosi di ogni nodo       │
 └────────────────────────────────────────┘                    └──────────────────────────────────┘
```

| Dove | Cosa serve | Si lancia con |
|---|---|---|
| Arduino UNO Q | repo clonato, `comms/.env`, certificato del Thing `nodo01` in `certs/` | `sudo ~/venv/bin/python comms/node/main.py` (o il servizio systemd) |
| PC | repo clonato, `app/.env`, certificato del Thing `mdgb-ingest` in `certs/` | `python app/central.py` |
| AWS IoT Core | due Thing (`nodo01`, `mdgb-ingest`) con le loro policy | si crea una volta con `comms/aws/setup_thing.sh` |

Il semaforo non passa mai da qui: lo comandano `ai/` (Paolo) e il firmware (Salvatore). Se questa rete si guasta,
il semaforo continua a funzionare.

## 1. Sul PC, senza hardware (10 min)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r comms/requirements.txt -r app/requirements.txt
brew install mosquitto
python -m pytest comms -q              # atteso: 26 passed (~45 s)
```

Tra i test c'è la prova completa "Wi-Fi spento / riacceso" con tempi accorciati (30 s → 2 s, 60 s → 3 s):
BLE acceso, diagnosi "rete giù, nodo sano", allarme via BLE in meno di 1 s, backfill, BLE spento, 0 eventi persi.

## 2. Demo locale sul PC (senza AWS e senza Arduino)

```bash
mosquitto -c app/mosquitto.conf                                        # terminale 1: broker locale
python app/central.py --no-ble                                         # terminale 2: centrale
python -m comms.tools.c3_sim --rate 2 --duration 3600                  # terminale 3: "ai/" finta
MQTT_HOST=localhost MQTT_PORT=1883 MQTT_TLS=0 EVENT_SOURCE=c3 python comms/node/main.py   # terminale 4: nodo
```

La centrale stampa ogni 10 s `STATO nodo01: nodo OK via mqtt`. Ctrl-C sul broker: il nodo scrive `rete=OFFLINE` e il
backlog cresce; dopo 30 s `backup ble ACCESO` (sul PC il BLE è simulato). Si riaccende il broker: backlog a 0, dopo
60 s `backup ble SPENTO`. `python app/central.py --report` deve dare `"gaps": 0`.

## 3. AWS IoT Core (una volta)

Serve: un account AWS (quello dello sponsor: chi lo gestisce?), l'AWS CLI installata e `aws configure` fatto **da te**
con le tue chiavi. Le chiavi AWS e i certificati non vanno mai in chat né nel repo (`certs/` e `.env` sono ignorati da git).

```bash
./comms/aws/setup_thing.sh nodo01      comms/aws/node-policy.json      # certificato del nodo
./comms/aws/setup_thing.sh mdgb-ingest comms/aws/ingest-policy.json    # certificato della centrale
cp comms/.env.example comms/.env     # MQTT_HOST = endpoint stampato dallo script
cp app/.env.example   app/.env       # stesso endpoint, certificato mdgb-ingest
```

Prova prima tutto dal PC: `python app/central.py --no-ble` in un terminale, `EVENT_SOURCE=sim python comms/node/main.py`
nell'altro. La centrale deve dire `nodo OK via mqtt`: vuol dire che nodo → AWS → centrale funziona.
Se la rete della sede blocca la porta 8883: `MQTT_PORT=443` in entrambi i `.env`.
Se AWS non è disponibile: Mosquitto sul PC (`MQTT_HOST=<IP del PC>`, `MQTT_PORT=1883`, `MQTT_TLS=0`), stesso codice.

## 4. Sulla UNO Q

```bash
ssh arduino@<ip-della-scheda>
git clone https://github.com/Paolo410/HackTurin-mdgb.git && cd HackTurin-mdgb
python3 -m venv ~/venv && ~/venv/bin/pip install -r comms/requirements.txt
which btmgmt && sudo btmgmt info       # il Bluetooth c'è e risponde?
```

Dal PC copia i file segreti sulla scheda:
`scp certs/nodo01.cert.pem certs/nodo01.private.key certs/AmazonRootCA1.pem comms/.env arduino@<ip>:HackTurin-mdgb/...`
(i certificati in `certs/`, il `.env` in `comms/`).

**Prima prova radio** (2 minuti, prima di tutto il resto):

```bash
sudo ~/venv/bin/python -m comms.tools.ble_beacon_test --seconds 60     # sulla UNO Q, dalla root del repo
python app/ble_receiver.py --node nodo01 --dry-run                     # sul PC
```

Il PC deve stampare un `HB` ogni 5 s con `backlog` che sale (10, 20, 30…). Su macOS la prima volta il terminale
chiede il permesso Bluetooth (Impostazioni → Privacy e sicurezza → Bluetooth).

**Avvio del nodo:** `sudo ~/venv/bin/python comms/node/main.py`. Il `sudo` serve a `btmgmt`.
Finché `ai/` di Paolo non scrive i suoi file, sulla scheda gira anche `~/venv/bin/python -m comms.tools.c3_sim --rate 1 --duration 7200`.
Avvio automatico: `comms/deploy/mdgb-comms.service` (istruzioni nel file).

## 5. Prova completa "Wi-Fi spento / riacceso" (sulla UNO Q)

Per la demo conviene `BACKUP_HB_S=30` in `comms/.env`: così si vede un HB via BLE ogni 30 s.

| Passo | Comando | Cosa deve succedere |
|---|---|---|
| 1 | PC: `python app/central.py` | `STATO nodo01: nodo OK via mqtt` |
| 2 | UNO Q: `sudo iptables -A OUTPUT -p tcp --dport 8883 -j DROP` (taglia solo MQTT, ssh resta su) | nodo: `rete=OFFLINE`, backlog che cresce |
| 3 | aspetta 30–40 s | nodo: `backup ble ACCESO`; PC: `STATO nodo01: rete giù, nodo sano via ble` |
| 4 | UNO Q: `sudo iptables -D OUTPUT -p tcp --dport 8883 -j DROP` | nodo: backlog che scende a 0 |
| 5 | aspetta 60 s | nodo: `backup ble SPENTO`; PC: `nodo OK via mqtt` |
| 6 | PC: `python app/central.py --report` | `"gaps": 0`: eventi inviati = ricevuti |

Con il Wi-Fi spento davvero cade anche ssh: lancia tutto in un colpo solo, per esempio
`sudo nohup sh -c 'nmcli radio wifi off; sleep 120; nmcli radio wifi on' &` (TODO(verify): `nmcli` sulla UNO Q).

## Cosa manca

| Cosa | Stato |
|---|---|
| Dashboard web sul PC (stato dei nodi, canale attivo, coda, conteggi, allarmi) | da fare: oggi lo stato si legge nel terminale della centrale e con `--report` |
| Prove su hardware vero: BLE sulla UNO Q (permessi, più beacon insieme, portata), AWS reale, Wi-Fi della sede | da fare, con i passi 3–5 |
| `ai/` di Paolo che scrive `logs/c3/c3-*.jsonl` (contratto C3) | da concordare; intanto `c3_sim` |
| Backup LoRa (Wio-E5) | dopo |
