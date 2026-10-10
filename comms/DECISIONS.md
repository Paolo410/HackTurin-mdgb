# comms/ e app/ — decisioni, numeri e interfacce

Owner: Lorenzo Dragoni (communication engineer). Aree: `comms/` (rete, sull'Arduino), `app/` (centrale, sul PC),
`docs/CONTRACTS.md` (formati dei messaggi). Stato al 10/10/2026.

Storia in una riga: l'idea iniziale era AWS IoT Core come broker; senza crediti AWS la demo usa un broker locale dentro
l'app della centrale. Il codice è lo stesso: in produzione basta puntare un broker MQTT 5 in cloud con TLS.

## 1. Decisioni prese

| Tema | Decisione |
|---|---|
| Sicurezza | Il nodo (Arduino UNO Q) decide in locale e comanda il semaforo tramite l'MCU. La rete serve solo a portare i dati alla centrale: se cade, il semaforo funziona lo stesso |
| Canale principale | MQTT 5 su Wi-Fi, QoS 1, Last Will, sessione persistente. **Demo**: broker Mosquitto dentro l'app sul PC (porta 1883, rete locale). **Produzione**: broker MQTT 5 in cloud con TLS e un certificato per nodo |
| Store & Forward | Ogni evento si scrive su disco (SQLite) **prima** dell'invio e si segna inviato solo dopo una conferma **positiva** del broker (PUBACK < 0x80). Al ritorno della rete la coda si svuota dal più vecchio |
| Numero dell'evento | `seq` persistente, mai riusato; `event_id` = `node_id` + `seq`. La centrale deduplica su `(node_id, seq)` e dai buchi vede i dati persi |
| "Online" | Solo se arrivano conferme (PUBACK positivo negli ultimi 30 s), non basta la connessione TCP |
| Backup | **BLE** (radio della UNO Q, beacon `btmgmt`) nella demo; **LoRaWAN** (Wio-E5 sull'MCU) in futuro. Solo allarmi, heartbeat e conteggi, mai i singoli eventi |
| Isteresi del backup | Acceso dopo 30 s senza conferme (subito heartbeat + conteggi + allarmi in sospeso); spento dopo 60 s di rete stabile. MQTT intanto riprova e recupera la coda |
| Centrale | Un'app per il PC (**Mac e Windows**), **MDGB Centrale**: broker + ricezione MQTT + ricezione Bluetooth diretta (senza Internet) + database + diagnosi + dashboard con mappa. Autonoma: un solo file, si sposta dove si vuole. L'exe per Windows lo costruisce GitHub Actions |
| Diagnosi | Incrociando MQTT e backup: OK / rete giù, nodo sano / nodo guasto / Linux bloccato / manomissione / batteria scarica / nodo spento o distrutto |
| Chi ha cosa | Sviluppatori: tutto il repo. Arduino: solo i 15 file di comms che girano lì (`comms/deploy/push_to_arduino.sh`, gli strumenti di collaudo solo con `--tools`) accanto alla visione di Paolo, in `~/HackTurin-mdgb`. Centralino: solo lo zip dell'app (Mac o Windows) |
| Niente finte sulla scheda | Il nodo legge solo i file veri di `ai/` e dell'MCU; BLE solo vero (senza BlueZ il nodo non parte); camere sulla mappa solo vere. Eventi di prova solo con `tools/c3_sim.py` lanciato a mano |
| Bridge (visione ↔ MCU) | `BridgeActuator` con la libreria ufficiale `arduino-router-bridge` (la stessa di App Lab, funziona da un venv normale): `call("mdgb_line")` per C1/C2, `provide("mcu_event")` per C5 |
| Mappa | Vettoriale (MapLibre + OpenFreeMap, gratis, senza chiave), stile chiaro/scuro/dettagliato; senza Internet mappa schematica. Google Maps solo con una chiave (facoltativo) |
| Privacy | Solo metadati anonimi verso la centrale. Unica eccezione (specifica §5.3): il video **dal vivo** della camera nell'app, in rete locale, se abilitato e mai registrato |
| Fuori scope | 4G / seconda SIM (solo nel pitch); LoRa (dopo la demo) |

## 2. Parametri e numeri

| Parametro | Valore |
|---|---|
| Topic | `mdgb/<node_id>/events` (batch fino a 50 eventi), `agg` (conteggi), `hb` (stato, ogni 10 s, retained + Last Will), `backup` |
| Broker demo | Mosquitto nell'app, porta 1883, aperto alla rete locale; l'app mostra l'indirizzo da dare all'Arduino |
| Timeout conferma | 30 s, poi il batch si rimanda; dopo un PUBACK negativo attesa crescente fino a 60 s |
| Riconnessione | backoff da 1 a 30 s; keepalive 30 s; sessione 3600 s |
| Backup | acceso dopo 30 s senza conferme, spento dopo 60 s stabili; heartbeat ogni 30 s (demo) / 5 min (produzione) |
| Conteggi | finestre di 60 s (demo) / 15 min (produzione) |
| Messaggi di backup | binari: `AGG` 26 byte, `HB` 12 byte, allarmi 5 byte; BLE: frame da 27 byte, fino a 3 beacon insieme (AGG, HB, allarmi) |
| Watchdog MCU | 5 min senza heartbeat da Linux → `DEAD` (solo con LoRa) |
| Retention | massimo 2.000.000 eventi su disco; si cancellano solo i più vecchi già inviati |

Formati completi con esempi: [`docs/CONTRACTS.md`](../docs/CONTRACTS.md).

## 3. Codice

| Dove | Cosa |
|---|---|
| `comms/node/` | il programma della rete sull'Arduino: Store & Forward, MQTT, backup BLE con isteresi, lettura degli eventi di `ai/` |
| `comms/actuators.py`, `comms/jsonl.py` | per `ai/`: comandi al semaforo e righe dell'MCU (Bridge sulla UNO Q, seriale, simulato sul PC) e scrittura dei file di eventi |
| `comms/tools/` | collaudo, solo a mano: `ble_beacon_test` (radio), `c1_send` (semaforo via Bridge o USB), `c3_sim` (eventi di prova) |
| `comms/deploy/` | `push_to_arduino.sh` (porta la rete sulla scheda, imposta il broker, `--service` per l'avvio automatico), servizio systemd |
| `app/` | la centrale: `central.py`, `ingest.py`, `diagnosis.py`, `dashboard.py`/`.html`, `decoder.py`, `ble_receiver.py` |
| `app/desktop/` | l'app per il PC e la sua costruzione (`build_mac.sh`) |
| `comms/tests/` | 38 test, tra cui il nodo vero che legge file reali, la prova "Wi-Fi spento / riacceso", un PUBACK negativo vero e il Bridge con la libreria ufficiale contro un router finto |

Provato: tutta la catena sul PC (broker vero, nodo vero con eventi di prova nei file, perdita di rete: 0 eventi persi);
il Bridge con la libreria ufficiale di Arduino; l'app costruita, firmata e avviata dallo zip; `push_to_arduino.sh` su una
"scheda finta" (cartella pulita, ssh simulato) con il nodo avviato da lì.
**Mai provato**: UNO Q vera, Bluetooth reale, sketch con `mdgb_line`, Wi-Fi della sede.

## 4. Cosa mi serve dagli altri

| Da chi | Cosa |
|---|---|
| Paolo | eventi C3 in `logs/c3/` (fatto con il suo `logger.py`); la visione sulla scheda in `~/HackTurin-mdgb/ai` |
| Salvatore | parser C1/C2 e fail-safe; nello sketch `Bridge.provide_safe("mdgb_line", ...)` e `Bridge.notify("mcu_event", riga)` per le righe C5 (ambiente, batteria, manomissione, guasto lampada, fail-safe) |
| Kuzey | pinout in `docs/CONTRACTS.md` (sportello, NFC, LTC2941, AHT20, luce) |

## 5. Cosa fornisco agli altri

Contratti (`docs/CONTRACTS.md`), la rete sulla scheda, `comms/actuators.py` e `comms/jsonl.py` per `ai/`, gli strumenti
di prova, l'app della centrale e le istruzioni (`docs/INSTRUCTIONS_FOR_OTHERS.md`).

## 6. Questioni aperte

1. **Bridge, lato sketch**: `mdgb_line` e `mcu_event` da Salvatore; il lato Linux è fatto. Prova: `c1_send --port bridge`.
2. **Prove su hardware**: Bluetooth della UNO Q (`btmgmt` con root, più beacon insieme, portata), permessi del socket
   `arduino-router` per l'utente della visione, rete della sede (dispositivi isolati? → hotspot o router vostro),
   firewall del Mac per le connessioni in entrata.
3. **`seq` dopo la perdita del database**: se il file del nodo si perde, `seq` riparte da 1 e la centrale scarterebbe i
   nuovi eventi come doppioni. Il database deve restare sulla scheda (`comms/node/data/`).
4. **Conteggi via MQTT segnati "inviati" troppo presto**: la finestra conta come pubblicata quando parte, non alla
   conferma; la centrale può comunque ricalcolarla dagli eventi.
5. **LoRa (dopo)**: lato MCU (`lora_send`, watchdog `DEAD`), decoder già pronto in `app/decoder.py`.
6. **Repo su iCloud**: il repo sul Desktop sincronizzato crea copie "… 2" dei file quando git li riscrive; meglio
   spostarlo fuori da Desktop/Documenti (es. `~/Developer/`).
