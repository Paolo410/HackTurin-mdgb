# Istruzioni per gli altri — rete e centrale (Lorenzo)

Cosa ho fatto, cosa dovete fare voi per collegarvi, e come si prepara tutto su PC e Arduino UNO Q.
Dettagli: [`comms/README.md`](../comms/README.md) (Arduino), [`app/README.md`](../app/README.md) (PC),
[`docs/CONTRACTS.md`](CONTRACTS.md) (formati dei messaggi, **è il riferimento per tutti**).

## 1. Il sistema in una figura

```
 ARDUINO UNO Q (sul semaforo)                                              PC DELLA CENTRALE
 ┌─────────────────────────────────────────────────────────┐              ┌──────────────────────────┐
 │ MCU: firmware (Salvatore) ── semaforo, LED, display      │              │ app "MDGB Centrale"      │
 │   ▲ C1 comandi, C2 heartbeat   │ C5 righe dell'MCU       │              │  - broker MQTT (demo)    │
 │   │ (seriale o Bridge)         ▼                         │   Wi-Fi      │  - database              │
 │ Linux: ai/ (Paolo) ── usa comms/actuators.py             │   MQTT       │  - dashboard con mappa   │
 │         └─ scrive gli eventi C3 in logs/c3/*.jsonl       │ ───────────► │  - diagnosi dei nodi     │
 │ Linux: comms/node/main.py (Lorenzo) legge logs/c3,       │   Bluetooth  │                          │
 │         salva su disco, invia; se il Wi-Fi è giù → BLE   │ ───────────► │                          │
 └─────────────────────────────────────────────────────────┘ (solo backup) └──────────────────────────┘
```

- La **sicurezza resta sulla scheda**: `ai/` decide, il firmware comanda il semaforo. La rete serve solo a portare i dati
  alla centrale: se cade, il semaforo funziona lo stesso.
- **Demo in locale**: il broker MQTT è dentro l'app sul PC, PC e Arduino stanno sulla stessa rete Wi-Fi.
  **In produzione** al posto del PC ci sarà un broker in cloud (AWS IoT Core o un altro broker MQTT 5) con TLS e un
  certificato per nodo: stesso codice, cambia solo la configurazione. Il backup BLE diventerà LoRaWAN.

## 2. Dopo il merge (tutti)

```bash
git switch main && git pull
```

Poi ognuno continua sul suo branch come da `PROMPT_GIT_TEAM.md`. Nessuna dipendenza nuova nelle vostre cartelle.
Io ho aggiunto al `.gitignore`: `certs/`, `*.db-wal`, `*.db-shm`, `mosquitto-data/`.

## 3. Paolo (`ai/`)

**Eventi verso la centrale (contratto C3).** Una riga JSON per evento, in file `logs/c3/c3-*.jsonl` (cartella `logs/`
nella root del repo, già ignorata da git). Il modo più semplice è usare il mio writer, che rispetta già le regole
(solo append, rotazione con nome nuovo, flush):

```python
import time
from comms.jsonl import JsonlWriter, default_c3_dir     # serve la root del repo nel path: PYTHONPATH=..

c3 = JsonlWriter(default_c3_dir(), "c3")
for ev in counter.update(tracked, roles, valid):        # i tuoi dict: type, track_id, cls, dir, line
    c3.write({"v": 1, "ts": time.time(), **ev})
c3.write({"v": 1, "ts": time.time(), "type": "status", "state": "PRESENCE", "fps": 9.6})   # ogni ~5 s
```

- I tuoi valori coincidono già con il contratto: `cls` = `pedestrian`, `cyclist`, `motorcyclist`, `car`, `bus`,
  `truck`, `animal`, `bird`; `dir` = `in`/`out`; `line` = `ped`/`veh`. Aggiungi `attrs` (`child`, `slow`, `aid`) quando arrivano.
- Altri tipi di riga: `near_miss`, `incident` (`kind` = `person_down`, `collision`, `hard_brake`, `vehicle_on_crosswalk`),
  `yield` (`yielded` true/false, per il tasso di precedenza). Gli `incident` arrivano in centrale **subito**, anche via BLE.
- Il mio programma (`comms/node/main.py`) legge i file da solo: non serve altro, e se uno dei due programmi si riavvia
  non si perde né si duplica nulla.

**Comandi al semaforo (contratti C1 e C2).** Usa `comms/actuators.py` dietro la tua opzione `--actuator`:

```python
from comms.actuators import make_actuator

act = make_actuator("serial", port="/dev/cu.usbmodem1101")   # "sim" senza hardware; "bridge" sulla UNO Q (da fare)
act.set_listener(on_mcu_line)    # facoltativo: righe C5 dall'MCU (env, tamper, lamp_fault, failsafe, thermal)
act.send(c1)                     # il dict di rules.py: al cambio di stato e comunque almeno ogni secondo
act.heartbeat(seq)               # ogni 100 ms: senza, dopo 500 ms il firmware va in fail-safe
```

`SimActuator().failsafe` ti dice se il firmware vero sarebbe in fail-safe (utile per l'overlay).
Da `ai/` lancia con la root del repo nel path: `PYTHONPATH=.. python -m smartcrossing.app ...`.

## 4. Salvatore (`firmware/`)

- **C1/C2** come in `docs/CONTRACTS.md`: una riga JSON per messaggio, al massimo 512 byte, seriale 115200 8N1.
  Niente heartbeat per più di 500 ms → fail-safe.
- **C5 (MCU → Linux)**: stampa sulla seriale righe JSON che iniziano con `{`; le altre righe sono debug e vengono ignorate.
  `{"v":1,"src":"mcu","type":"env","t_c":14.2,"rh":81,"lux":120,"batt":87}` ogni 10 s (batteria dal LTC2941),
  `{"v":1,"src":"mcu","type":"tamper","code":2}` (1 urto, 2 sportello aperto, 3 badge NFC del tecnico),
  `{"v":1,"src":"mcu","type":"lamp_fault",...}`, `{"v":1,"src":"mcu","type":"failsafe","reason":"hb_timeout"}`.
  Le scrivo io su file e arrivano in centrale (gli allarmi subito, anche via BLE).
- **Bridge sulla UNO Q** (proposta da confermare insieme): `Bridge.provide_safe("mdgb_line", ...)` riceve le stesse
  righe C1/C2 della seriale; per C5 `Bridge.notify("mcu_event", riga)`.
- **Prova dal PC** con la scheda in USB:
  `python -m comms.tools.c1_send --port /dev/cu.usbmodemXXXX --duration 30 --stop-hb-at 20`
  (cicla gli stati, heartbeat a 10 Hz, a 20 s toglie l'heartbeat: il firmware deve andare in fail-safe entro 500 ms).
- Il Bluetooth di backup lo gestisce il lato Linux (`btmgmt`): al firmware non serve nulla. LoRa più avanti.

## 5. Kuzey (`hardware/`)

Compila la sezione **Pinout** di `docs/CONTRACTS.md` con: micro switch dello sportello, lettore NFC, LTC2941 (batteria),
AHT20 e sensore di luce. Il modulo LoRa (Wio-E5) serve solo più avanti.

## 6. Chi ha cosa

| Chi | Cosa riceve | Come |
|---|---|---|
| Sviluppatori | tutto il repo | `git pull` |
| Arduino UNO Q | solo il codice che gira sulla scheda: la rete in `~/mdgb/comms` (Lorenzo) e la visione in `~/mdgb/ai` (Paolo); il firmware sull'MCU (Salvatore) | `comms/deploy/push_to_arduino.sh` per la rete; Paolo e Salvatore per le loro parti |
| Centralino (PC) | solo l'app, `MDGB-Centrale-mac.zip` (broker incluso) | `./app/desktop/build_mac.sh` sul Mac dello sviluppatore, poi lo zip via AirDrop/chiavetta |

Il centralino apre l'app (la prima volta clic destro → Apri), consente Bluetooth e connessioni in entrata. In alto compare
**`Arduino → 192.168.x.y:1883`**: è l'indirizzo da mettere nella configurazione dell'Arduino.

## 7. Arduino UNO Q

L'UNO Q ha Linux (Debian) a bordo. Serve una volta sola:

1. **Wi-Fi e IP**: con Arduino App Lab (primo avvio della scheda) collega la UNO Q **alla stessa rete Wi-Fi del PC**.
   Sulla scheda `hostname -I` dice il suo indirizzo. Se la rete della sede isola i dispositivi (il PC non vede la scheda),
   usate l'hotspot di un telefono o un router vostro per PC e scheda.
2. **Accesso**: dal PC `ssh arduino@<IP della scheda>` (utente e password scelti al primo avvio; `TODO(verify)` il nome utente).
3. **Rete (Lorenzo)**: dal PC dello sviluppatore, nella cartella del repo. Copia in `~/mdgb/comms` solo i file della rete,
   crea `~/venv` e installa le dipendenze (serve Internet sulla scheda la prima volta):
   ```bash
   ./comms/deploy/push_to_arduino.sh arduino@<IP della scheda>
   ```
   Senza ssh: `./comms/deploy/push_to_arduino.sh --pack` crea `mdgb-nodo.tar.gz` da copiare e scompattare in `~/mdgb`.
4. **Visione (Paolo)**: il codice di `ai/` va in `~/mdgb/ai`, accanto a `comms`, con le sue dipendenze
   (`~/venv/bin/pip install -r ~/mdgb/ai/requirements.txt`). Così scrive gli eventi in `~/mdgb/logs/c3/` e importa
   `comms.actuators`. Il modello (`ai/models/`) si copia a parte.
5. **Configurazione della rete**: `nano ~/mdgb/comms/.env` e in `MQTT_HOST` scrivi l'IP mostrato dall'app sul PC.
6. **Prima prova del Bluetooth** (2 minuti): sulla scheda
   `cd ~/mdgb && sudo ~/venv/bin/python -m comms.tools.ble_beacon_test --seconds 60`; sul PC dello sviluppatore, nello
   stesso momento, `python app/ble_receiver.py --node nodo01 --dry-run` deve stampare un heartbeat ogni 5 s.
7. **Avvio**: tre programmi sulla scheda.
   - firmware sull'MCU: lo carica Salvatore (App Lab o Arduino IDE);
   - visione: `cd ~/mdgb/ai && PYTHONPATH=.. ~/venv/bin/python -m smartcrossing.app --profile unoq --headless` (Paolo);
   - rete: `sudo ~/venv/bin/python ~/mdgb/comms/node/main.py`.

   Finché la visione non scrive i suoi file, al suo posto: `cd ~/mdgb && ~/venv/bin/python -m comms.tools.c3_sim --rate 1 --duration 7200`.
   Avvio automatico della rete all'accensione: `comms/deploy/mdgb-comms.service`.

## 8. Dal nodo simulato a quello vero

Il nodo vero è **`nodo01`**: in `app/nodes.json` è l'unica camera con `mock: false`, e sulla scheda `comms/.env` ha
`NODE_ID=nodo01`. La sua posizione sulla mappa si cambia dall'app (pulsante **Cartella** → `nodes.json`, `lat`/`lon`).
La rete e l'app restano uguali in tutte le fasi: cambia solo chi produce gli eventi.

| Fase | Cosa gira sulla scheda | Cosa si vede nell'app |
|---|---|---|
| Oggi (sviluppo sul PC) | niente: nodo simulato sul PC (`EVENT_SOURCE=sim`) | `nodo01` verde, eventi finti |
| Scheda con la rete, senza visione | `comms/node/main.py` + `comms.tools.c3_sim` | `nodo01` verde, eventi finti ma via Wi-Fi e Bluetooth veri |
| Visione pronta (Paolo) | `comms/node/main.py` + `smartcrossing.app` (si toglie `c3_sim`) | conteggi, incidenti, near-miss, precedenza e stato del semaforo **veri** |
| Firmware pronto (Salvatore) | in più l'MCU manda le righe C5 tramite `comms/actuators.py` | batteria, ambiente, manomissione, guasto lampada e fail-safe **veri** |

Chi produce cosa nella dashboard:

| Nella dashboard | Da dove arriva |
|---|---|
| traffico (pedoni, ciclisti, veicoli, animali), incidenti, near-miss, precedenza, pedoni vulnerabili | Paolo, righe C3 in `logs/c3/` |
| stato del semaforo e FPS | Paolo, riga `status` ogni ~5 s |
| batteria, temperatura/umidità/luce, manomissione, guasto lampada, fail-safe | Salvatore, righe C5 dell'MCU |
| canale (Wi-Fi o Bluetooth), coda, eventi persi, doppioni, diagnosi "rete giù / nodo sano / ..." | Lorenzo, la rete |

Le camere `nodo02`…`nodo05` sono il mockup: restano grigie ("mockup, nessun dato"). Per la demo si possono accendere con
nodi simulati sul PC (vedi `app/README.md`) oppure togliere da `nodes.json`.

## 9. Prova completa "Wi-Fi spento / riacceso"

| Passo | Dove | Cosa | Cosa si vede nell'app |
|---|---|---|---|
| 1 | PC | app aperta, nodo acceso | camera verde, "nodo OK", canale Wi-Fi/MQTT |
| 2 | UNO Q | `sudo iptables -A OUTPUT -p tcp --dport 1883 -j DROP` (taglia solo MQTT, ssh resta su) | coda del nodo che cresce |
| 3 | — | aspetta 30–40 s | camera gialla, "rete giù, nodo sano", canale BLE con il segnale |
| 4 | UNO Q | `sudo iptables -D OUTPUT -p tcp --dport 1883 -j DROP` | coda che torna a 0 |
| 5 | — | aspetta 60 s | camera di nuovo verde via Wi-Fi/MQTT |
| 6 | PC | riquadro "Rete" | **Eventi persi = 0** |

Per la demo davanti alla giuria si può anche spegnere davvero il Wi-Fi della scheda (cade anche ssh):
`sudo nohup sh -c 'nmcli radio wifi off; sleep 120; nmcli radio wifi on' &` (`TODO(verify)`: `nmcli` sulla UNO Q).

## 10. Cosa manca (comms)

- Prove su hardware vero: Bluetooth della UNO Q (permessi, portata), rete della sede.
- `BridgeActuator` (comandi via Bridge sulla UNO Q), insieme a Salvatore.
- Backup LoRa e broker in cloud: dopo l'hackathon, stesso codice.
