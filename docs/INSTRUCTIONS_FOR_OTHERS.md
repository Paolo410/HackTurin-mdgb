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
 │   │        (Bridge)            ▼                         │   Wi-Fi      │  - database              │
 │ Linux: ai/ (Paolo) ── usa comms/actuators.py             │   MQTT       │  - dashboard con mappa   │
 │         └─ scrive gli eventi C3 in logs/c3/*.jsonl       │ ───────────► │  - diagnosi dei nodi     │
 │ Linux: comms/node/main.py (Lorenzo) legge logs/c3,       │   Bluetooth  │                          │
 │         salva su disco, invia; se il Wi-Fi è giù → BLE   │ ───────────► │                          │
 └─────────────────────────────────────────────────────────┘ (solo backup) └──────────────────────────┘
```

- La **sicurezza resta sulla scheda**: `ai/` decide, il firmware comanda il semaforo. La rete serve solo a portare i dati
  alla centrale: se cade, il semaforo funziona lo stesso.
- **Demo in locale**: il broker MQTT (Mosquitto, MQTT vero) è dentro l'app sul PC; PC e Arduino stanno sulla stessa rete
  Wi-Fi. **In produzione** al posto del PC ci sarà un broker MQTT 5 in cloud con TLS e un certificato per nodo: stesso
  codice, cambia solo la configurazione. Il backup BLE diventerà LoRaWAN.
- **Niente simulazioni sulla scheda**: il nodo legge solo gli eventi veri della visione e dell'MCU, il Bluetooth è
  quello della UNO Q (se manca, il nodo non parte e lo dice), il Bridge usa la libreria ufficiale di Arduino.

## 2. Dopo il merge (tutti)

```bash
git switch main && git pull
```

Poi ognuno continua sul suo branch come da `PROMPT_GIT_TEAM.md`. Nessuna dipendenza nuova nelle vostre cartelle.
In `comms/requirements.txt` c'è `arduino-router-bridge` (il Bridge, libreria ufficiale di Arduino): sulla scheda lo
installa `push_to_arduino.sh` nello stesso `~/venv` della visione.
Io ho aggiunto al `.gitignore`: `certs/`, `*.db-wal`, `*.db-shm`, `mosquitto-data/`.

## 3. Paolo (`ai/`)

**Eventi verso la centrale (contratto C3).** Una riga JSON per evento, in file `logs/c3/c3-*.jsonl` (cartella `logs/`
nella root del repo, già ignorata da git). Il tuo `logger.py` lo fa già. La rete (`comms/node/main.py`) legge i file da
sola: se uno dei due programmi si riavvia non si perde né si duplica nulla.

- Valori del contratto: `cls` = `pedestrian`, `cyclist`, `motorcyclist`, `car`, `bus`, `truck`, `animal`, `bird`;
  `dir` = `in`/`out`; `line` = `ped`/`veh`; `attrs` (`child`, `slow`, `aid`).
- Altri tipi di riga: `near_miss`, `incident` (`kind` = `person_down`, `collision`, `hard_brake`, `vehicle_on_crosswalk`),
  `yield` (`yielded` true/false), `status` ogni ~5 s (stato e FPS). Gli `incident` arrivano in centrale **subito**, anche via BLE.

**Comandi al semaforo (contratti C1 e C2).** Il tuo `--actuator bridge` ora funziona: usa `BridgeActuator` di
`comms/actuators.py`, che parla con l'MCU attraverso il servizio `arduino-router` della scheda.

```python
from comms.actuators import make_actuator

act = make_actuator("bridge")    # sulla UNO Q; "serial" (port=...) per un Arduino in USB, "sim" senza hardware
act.set_listener(on_mcu_line)    # righe C5 dall'MCU (env, tamper, lamp_fault, failsafe, thermal)
act.send(c1)                     # al cambio di stato e comunque almeno ogni secondo
act.heartbeat(seq)               # ogni 100 ms: senza, dopo 500 ms il firmware va in fail-safe
```

`send` e `heartbeat` non bloccano mai e non sollevano eccezioni: se il router o lo sketch non rispondono, lo scrivono
nel log e riprovano; il firmware intanto resta nel ciclo normale (fail-safe). Il tuo `ai/deploy/mdgb-ai.service`
(`--actuator bridge`) va bene così.

**Sulla scheda solo il codice che gira lì.** La tua guida (`ai/docs/DEPLOY_UNOQ.md`) fa `git clone` di tutto il repo: così
sulla scheda finirebbero anche l'app del PC e la documentazione (e il repo è privato: servirebbe un token sulla scheda).
Proposta: copiare dal PC solo `ai/`, come faccio io con `comms/`, per esempio
`rsync -a --exclude __pycache__ ai arduino@<IP>:~/HackTurin-mdgb/` (modello e `calib.json` compresi). Decidi tu.

**Se sulla scheda gira anche l'app di App Lab di Salvatore**, gli eventi vanno nella sua cartella, dove li legge la rete:
nel tuo servizio `Environment=MDGB_C3_DIR=/home/arduino/ArduinoApps/<cartella>/data/c3` (oppure `--c3-dir`).

**Video dal vivo nell'app (facoltativo, specifica §5.3: solo live, solo in locale, solo se abilitato).** Se la visione
espone uno stream **MJPEG** con l'overlay, per esempio `http://<IP scheda>:8090/stream.mjpg`
(`Content-Type: multipart/x-mixed-replace`), nell'app basta mettere quell'indirizzo nel campo `video` della camera in
`nodes.json`: compare "Guarda dal vivo". Lo stream non va mai salvato su disco.

## 4. Salvatore (`firmware/`)

**Con la tua app di App Lab (sketch + `main.py`)**, per mandare sensori e allarmi alla centrale:

1. trascina `comms/applab/mdgb_link.py` e `comms/applab/main.py` nella cartella `python/` della tua app in App Lab
   (il `main.py` è il tuo, uguale, con 5 righe in più che inoltrano i dati a `mdgb_link`); lo sketch non cambia;
2. avvia l'app; sulla scheda `ls ~/ArduinoApps` dice il nome della sua cartella;
3. Lorenzo: `./comms/deploy/push_to_arduino.sh arduino@<IP> --service --applab <cartella>`.

Il Bluetooth di backup non può girare dentro App Lab (container senza Bluetooth): per questo la rete è un servizio a
parte sulla stessa scheda, che legge quello che scrive `mdgb_link.py`. Cosa arriva in centrale: ambiente ogni 10 s,
"manomissione: urto" per il tentato furto, "badge del tecnico" per l'accesso consentito (`comms/README.md`).
Attenzione: il tuo `main.py` apre la camera, che serve anche alla visione di Paolo: nella demo finale va deciso chi la usa.

**Per il semaforo comandato dalla visione** servono in più due cose nello sketch (libreria
[Arduino_RouterBridge](https://github.com/arduino-libraries/Arduino_RouterBridge), nomi in `docs/CONTRACTS.md`):

```cpp
#include <Arduino_RouterBridge.h>

// C1 o C2, una riga JSON senza '\n': stesso parser della seriale. true = riga valida.
bool mdgb_line(String line) {
  return parse_c1_c2(line);
}

void setup() {
  Bridge.begin();
  Bridge.provide_safe("mdgb_line", mdgb_line);   // provide_safe: gira dentro loop(), niente race con LED e centralina
}

// C5 verso Linux, quando succede qualcosa (e "env" ogni 10 s):
//   Bridge.notify("mcu_event", "{\"v\":1,\"src\":\"mcu\",\"type\":\"failsafe\",\"reason\":\"hb_timeout\"}");
```

- **C1/C2** come in `docs/CONTRACTS.md`: al massimo 512 byte. Niente heartbeat per più di 500 ms → fail-safe.
- **C5**: `env` (`t_c`, `rh`, `lux`, `batt`) ogni 10 s; `tamper` (`code` 1 urto, 2 sportello, 3 badge NFC);
  `lamp_fault`; `failsafe` (`reason`). `actuators.py` le scrive su file e la rete le porta in centrale (gli allarmi subito,
  anche via BLE). Nel loop non chiamare `Bridge.call` dentro `mdgb_line` (rischio di deadlock, lo dice la libreria).
- **Prova sulla scheda** (con la visione ferma: `sudo systemctl stop mdgb-ai`), dopo `push_to_arduino.sh ... --tools`:
  `cd ~/HackTurin-mdgb && ~/venv/bin/python -m comms.tools.c1_send --port bridge --duration 30 --stop-hb-at 20`.
  Cicla gli stati del semaforo, heartbeat a 10 Hz, a 20 s lo toglie (fail-safe entro 500 ms), stampa le righe C5 e alla
  fine dice se l'MCU ha risposto (`-> OK`). Con un Arduino in USB dal PC: `--port /dev/cu.usbmodemXXXX`.
- Il Bluetooth di backup lo gestisce il lato Linux (`btmgmt`): al firmware non serve nulla. LoRa più avanti.

## 5. Kuzey (`hardware/`)

Compila la sezione **Pinout** di `docs/CONTRACTS.md` con: micro switch dello sportello, lettore NFC, LTC2941 (batteria),
AHT20 e sensore di luce. Il modulo LoRa (Wio-E5) serve solo più avanti.

## 6. Chi ha cosa

| Chi | Cosa riceve | Come |
|---|---|---|
| Sviluppatori | tutto il repo | `git pull` |
| Arduino UNO Q | solo il codice che gira sulla scheda: la rete in `~/HackTurin-mdgb/comms` (15 file), la visione in `~/HackTurin-mdgb/ai`, il firmware sull'MCU | `comms/deploy/push_to_arduino.sh` (Lorenzo); Paolo e Salvatore per le loro parti |
| Centralino (PC Mac o Windows) | solo l'app: `MDGB-Centrale-mac.zip` o `MDGB-Centrale-windows.zip` (broker incluso, nessuna installazione) | Mac: `./app/desktop/build_mac.sh`; Windows: GitHub → Actions → "App centrale per Windows" → Artifacts. Poi lo zip via chiavetta/mail |

Il centralino apre l'app (la prima volta: Mac clic destro → Apri; Windows "Ulteriori informazioni" → "Esegui comunque"),
consente Bluetooth e connessioni in entrata (Firewall di Windows: reti private). In alto compare
**`Arduino → 192.168.x.y:1883`**: è l'indirizzo del broker, che `push_to_arduino.sh` mette da solo nella configurazione
dell'Arduino se lo lanci da quel PC.

## 7. Arduino UNO Q

L'UNO Q ha Linux (Debian) a bordo. Serve una volta sola:

1. **Wi-Fi e IP**: con Arduino App Lab (primo avvio della scheda) collega la UNO Q **alla stessa rete Wi-Fi del PC**.
   Sulla scheda `hostname -I` dice il suo indirizzo. Se la rete della sede isola i dispositivi (il PC non vede la scheda),
   usate l'hotspot di un telefono o un router vostro per PC e scheda.
2. **Accesso**: dal PC `ssh arduino@<IP della scheda>` (utente e password scelti al primo avvio; `TODO(verify)` il nome
   utente). **Cartella comune: `~/HackTurin-mdgb`** (la usa anche la guida di Paolo): la visione scrive gli eventi in
   `~/HackTurin-mdgb/logs/c3/` e la rete li legge da lì.
3. **Rete (Lorenzo)**, con l'app della centrale aperta, dal PC nella cartella del repo:
   ```bash
   ./comms/deploy/push_to_arduino.sh arduino@<IP della scheda> --service --tools
   ```
   Copia solo i file della rete, crea `~/venv` con le dipendenze, scrive `comms/.env` con il broker = questo PC,
   installa l'avvio automatico e fa partire il nodo (chiede la password di sudo). Senza ssh: `--pack` crea
   `mdgb-nodo.tar.gz` da copiare a mano. `--tools` serve solo al collaudo (punto 5): quando tutto va, si può rilanciare senza.
4. **Visione (Paolo)**: `ai/docs/DEPLOY_UNOQ.md` (stesso `~/venv`, modello e calibrazione, servizio `ai/deploy/mdgb-ai.service`).
5. **Collaudo**, nell'ordine:
   - **rete**: `journalctl -u mdgb-comms -f` sulla scheda mostra `backup BLE reale (btmgmt)` e poi `rete=ONLINE`;
     nell'app la camera `nodo01` diventa verde;
   - **Bluetooth** (2 minuti): `sudo systemctl stop mdgb-comms`, poi
     `cd ~/HackTurin-mdgb && sudo ~/venv/bin/python -m comms.tools.ble_beacon_test --seconds 60`: nell'app la camera
     mostra il canale BLE con il segnale; poi `sudo systemctl start mdgb-comms`;
   - **semaforo via Bridge** (Salvatore): `c1_send --port bridge`, vedi sezione 4;
   - **tutto insieme**: visione + firmware + rete, poi la prova della sezione 9.

   Finché la visione non scrive i suoi file, la rete si prova con eventi di prova scritti negli stessi file:
   `cd ~/HackTurin-mdgb && ~/venv/bin/python -m comms.tools.c3_sim --rate 1 --duration 7200`.

## 8. Cosa è vero e cosa è di prova

| Parte | Sulla scheda / nell'app |
|---|---|
| MQTT | vero: Mosquitto (broker MQTT 5) dentro l'app sul PC, il nodo si collega via Wi-Fi |
| Bluetooth | vero: beacon della radio della UNO Q (`btmgmt`), ricevuti dal Bluetooth del PC. Senza BlueZ il nodo non parte |
| Bridge (visione ↔ MCU) | vero: libreria ufficiale `arduino-router-bridge`. Manca solo il lato sketch (sezione 4) |
| Eventi | veri: il nodo legge solo i file scritti dalla visione e dall'MCU. Di prova solo se lanci a mano `c3_sim` |
| Camere sulla mappa | solo `nodo01`, il nodo vero (posizione da cambiare in `nodes.json` dall'app, pulsante **Cartella**). Un altro Arduino con un altro `NODE_ID` compare da solo |

Chi produce cosa nella dashboard:

| Nella dashboard | Da dove arriva |
|---|---|
| traffico (pedoni, ciclisti, veicoli, animali), incidenti, near-miss, precedenza, pedoni vulnerabili | Paolo, righe C3 in `logs/c3/` |
| stato del semaforo e FPS | Paolo, riga `status` ogni ~5 s |
| batteria, temperatura/umidità/luce, manomissione, guasto lampada, fail-safe | Salvatore, righe C5 dell'MCU |
| canale (Wi-Fi o Bluetooth), coda, eventi persi, doppioni, diagnosi "rete giù / nodo sano / ..." | Lorenzo, la rete |

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

## 10. Cosa manca

- **Salvatore**: `mdgb_line` e `Bridge.notify("mcu_event", ...)` nello sketch (sezione 4).
- **Paolo**: la visione sulla scheda (sezione 3).
- **Prove su hardware vero** (mai fatte finora): Bluetooth della UNO Q (permessi, più beacon insieme, portata), permessi
  del socket `arduino-router` per l'utente della visione, rete della sede.
- Backup LoRa e broker in cloud: dopo l'hackathon, stesso codice.
