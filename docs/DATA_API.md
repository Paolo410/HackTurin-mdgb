# Dati in uscita dalla centrale: API per i clienti e MQTT

Scritto da Paolo (data scientist) con il codice in `app/customers.py`, `app/publisher.py` e `ai/forecast/`.
**Da far vedere a Lorenzo**: sono interfacce nuove, non cambiano i contratti C1–C5 di [`CONTRACTS.md`](CONTRACTS.md);
se le approva, lì va aggiunto un rimando a questo file.

La centrale riceve dai nodi solo conteggi anonimi (contratto C4). Con quelli calcola metriche e previsioni
([`ai/forecast/`](../ai/forecast/README.md)) e le rende disponibili in due modi:

| Per chi | Come | Cosa |
|---|---|---|
| Clienti (un negozio, il Comune) | HTTP con chiave API, `GET /api/v1/...` | dati in tempo reale e previsti delle camere della **loro zona** |
| Altri sistemi sulla stessa rete | MQTT, `mdgb/<nodo>/forecast` e `mdgb/<nodo>/analytics` | stima, previsione e metriche di ogni camera |

Non escono mai immagini, eventi singoli o identificativi di persone: solo conteggi per attraversamento.

## Chiavi API

Una chiave appartiene a un cliente e vale per una **zona**: un cerchio sulla mappa (centro e raggio, da 50 m a 20 km)
oppure un elenco di nodi. Con la chiave si leggono i dati delle camere che stanno nella zona; se non ce ne sono
ancora, le risposte dicono `"available": false` e i dati compaiono da soli quando una camera viene installata lì.

- **Dalla dashboard** (solo sul PC della centrale): scheda "Dati per i clienti" in fondo alla pagina. Si sceglie una
  camera sulla mappa, si scrivono nome del cliente, raggio e durata, e la chiave compare una volta sola.
- **Da terminale**, anche ad app aperta:

```bash
python app/customers.py create --name "Bar Sport" --lat 45.0614 --lon 7.6581 --radius 400 --days 30
python app/customers.py create --name "Comune di Torino" --nodes nodo01,nodo02
python app/customers.py list
python app/customers.py revoke 1a89b548
```

  Con l'app impacchettata il database è `central.db` nella cartella delle impostazioni: `--db "<cartella>/central.db"`.

Cosa c'è da sapere:

- La chiave ha la forma `mdgb_<id>_<segreto>`. Nel database resta solo la sua impronta (SHA-256): chi legge il database
  non può ricostruirla, e se il cliente la perde se ne crea un'altra.
- Tipi di dati per chiave: `realtime` (conteggi, storico, metriche) e `forecast` (previsioni). Di base entrambi;
  da terminale `--scopes forecast` ne dà uno solo.
- Scadenza facoltativa, revoca immediata.
- Al massimo 120 richieste al minuto per chiave.
- Ogni richiesta servita viene contata per chiave, giorno e tipo di dato (tabella `api_usage`): è la base per
  misurare l'uso e, un domani, per farlo pagare.
- Le chiavi si creano, elencano e revocano solo dal PC della centrale (`/api/keys` risponde 403 a chiunque altro),
  anche quando la dashboard è aperta alla rete locale.

## API per i clienti (versione 1)

Indirizzo: `http://<PC della centrale>:8080/api/v1/`. Di base la centrale ascolta solo sul proprio PC; per farla
raggiungere dalla rete serve `WEB_HOST=0.0.0.0` nelle impostazioni. **Fuori da una rete fidata va messa dietro HTTPS**
(un proxy con certificato): la chiave viaggia nell'intestazione e in HTTP semplice si può leggere.

Due avvertenze per chi la espone:

- Il proxy deve inoltrare **solo `/api/v1/`**. La gestione delle chiavi (`/api/keys`) riconosce il PC della centrale
  dall'indirizzo di chi chiama: dietro un proxy sulla stessa macchina ogni richiesta sembra locale.
- Il resto della dashboard (`/`, `/api/state`, `/api/flow`) non ha chiavi: è pensato per chi controlla gli
  attraversamenti, sulla rete della centrale.

La chiave va in un'intestazione, mai nell'indirizzo:

```bash
curl -H "X-API-Key: mdgb_1a89b548_..." http://localhost:8080/api/v1/forecast
curl -H "Authorization: Bearer mdgb_1a89b548_..." "http://localhost:8080/api/v1/history?hours=6&format=csv" -o conteggi.csv
```

| Indirizzo | Tipo di dati | Cosa restituisce |
|---|---|---|
| `GET /api/v1/` | senza chiave | descrizione dell'API |
| `GET /api/v1/zone` | qualsiasi | la zona della chiave, le camere che contiene, la scadenza |
| `GET /api/v1/realtime` | `realtime` | per camera: ultima finestra contata, ultima ora, stima di adesso all'ora con intervallo; totale della zona |
| `GET /api/v1/forecast?hours=24` | `forecast` | per camera e per la zona: previsione ora per ora (1–24 ore); `&format=csv` |
| `GET /api/v1/history?hours=24` | `realtime` | per camera: le finestre contate (1–24 ore); `&format=csv` |
| `GET /api/v1/metrics` | `realtime` | per camera: traffico delle ultime 24 ore, sicurezza, verifica della stima |

In ogni risposta: `zone`, `available` (ci sono camere nella zona), `generated_at` (secondi epoch UTC) e
`generated_at_iso`. I tempi sono sempre in secondi epoch UTC, con accanto la forma ISO (`t0_iso`). I conteggi sono
`ped_in`, `ped_out` (pedoni nei due versi), `cyclist`, `vehicles`.

Errori, sempre `{"error": "..."}`:

| Codice | Quando |
|---|---|
| 401 | chiave mancante, malformata, sconosciuta, scaduta o revocata |
| 403 | la chiave non comprende quel tipo di dati |
| 429 | più di 120 richieste in un minuto (`Retry-After: 60`) |

### `/api/v1/realtime`

```json
{"available": true, "generated_at": 1791820800.0, "generated_at_iso": "2026-10-12T16:00:00Z",
 "zone": {"lat": 45.0614, "lon": 7.6581, "radius_m": 500},
 "cameras": [{
   "id": "nodo01", "name": "Corso Castelfidardo, incrocio corso Luigi Einaudi", "lat": 45.0614, "lon": 7.6581, "distance_m": 0,
   "last_data_s": 0,
   "last_window": {"t0": 1791820740, "t0_iso": "2026-10-12T15:59:00Z", "t1": 1791820800,
                   "ped_in": 4, "ped_out": 2, "cyclist": 0, "vehicles": 1, "provisional": false},
   "last_hour": {"ped_in": 240, "ped_out": 120, "cyclist": 0, "vehicles": 60},
   "estimate_from": "model_and_counts",
   "estimate_per_hour": {"ped_in": {"mean": 234.5, "low": 206.6, "high": 263.2}, "ped_out": {"mean": 117.8, "low": 101.8, "high": 134.2},
                         "cyclist": {"mean": 2.8, "low": 1.7, "high": 3.9}, "vehicles": {"mean": 60.7, "low": 49.8, "high": 72.2}}}],
 "zone_estimate_per_hour": {"ped_in": 234.5, "ped_out": 117.8, "cyclist": 2.8, "vehicles": 60.7},
 "notice_model": "Stime e previsioni vengono da un modello addestrato su uno storico simulato ..."}
```

- `last_window`, `last_hour`: conteggi misurati dalla camera; `null` se non ha ancora mandato dati.
  `provisional: true` = finestra arrivata sul canale di riserva (Bluetooth), sostituita da quella esatta appena torna la rete.
- `last_data_s`: secondi dall'ultima finestra ricevuta. Se cresce, la camera non sta contando.
- `estimate_per_hour`: stima del flusso di adesso, in passaggi all'ora, con intervallo all'80%.
  `estimate_from`: `model_and_counts` se corretta con i conteggi recenti, `model_only` se la camera tace.

### `/api/v1/forecast`

```json
{"available": true, "zone": {"lat": 45.0614, "lon": 7.6581, "radius_m": 500},
 "cameras": [{"id": "nodo01", "name": "Corso Castelfidardo, incrocio corso Luigi Einaudi", "distance_m": 0,
              "hours": [{"t0": 1791824400, "t0_iso": "2026-10-12T17:00:00Z", "t1": 1791828000,
                         "ped_in": 173.5, "ped_out": 80.1, "cyclist": 1.8, "vehicles": 44.5},
                        {"t0": 1791828000, "t0_iso": "2026-10-12T18:00:00Z", "t1": 1791831600,
                         "ped_in": 141.0, "ped_out": 53.2, "cyclist": 0.9, "vehicles": 28.2}]}],
 "zone_hours": [{"t0": 1791824400, "t0_iso": "2026-10-12T17:00:00Z", "t1": 1791828000,
                 "ped_in": 173.5, "ped_out": 80.1, "cyclist": 1.8, "vehicles": 44.5}]}
```

Una riga per ora di orologio, dalla prossima in poi: passaggi attesi in quell'ora. `zone_hours` è la somma delle
camere della zona. In CSV: `camera,name,t0,t0_iso,t1,ped_in,ped_out,cyclist,vehicles`.

### `/api/v1/metrics`

Per camera, `metrics.traffic` (ultima ora, oggi, ultime 24 ore, ora per ora con `coverage` = quota dell'ora davvero
misurata, ora di punta, quota di pedoni in un verso), `metrics.safety` (attraversamenti, pedoni fragili, veicoli che
hanno dato la precedenza, quasi incidenti per 1000 attraversamenti, incidenti per tipo) e `estimate_check`:

```json
{"windows": 48, "window_s": 60, "mean_count": 6.0, "mae": 0.15, "mae_persistence": 0.0, "mae_model": 4.89, "bias": -0.025}
```

Ogni finestra già contata è stata stimata con i soli dati disponibili prima che iniziasse. `mae` è l'errore medio
della stima in pedoni per finestra; `mae_persistence` quello che si otterrebbe ripetendo l'ultimo conteggio;
`mae_model` quello del solo modello, senza la camera. `null` finché le finestre contate sono meno di venti.

## MQTT

Ogni 30 secondi (`ANALYTICS_PERIOD_S` nelle impostazioni; 0 = spento) la centrale pubblica sul proprio broker, per
ogni camera, due messaggi JSON con QoS 1 e **retained**: chi si collega riceve subito l'ultimo valore.

| Argomento | Contenuto |
|---|---|
| `mdgb/<nodo>/forecast` | stima di adesso e previsione delle prossime 24 ore, in passaggi all'ora |
| `mdgb/<nodo>/analytics` | metriche delle ultime 24 ore e verifica della stima (come `/api/v1/metrics`) |

Il prefisso `mdgb` segue `TOPIC_PREFIX`. Sono argomenti diversi da quelli che i nodi pubblicano e la centrale ascolta
(`events`, `agg`, `hb`, `backup`): non rientrano mai nell'ingest.

```bash
mosquitto_sub -h <PC della centrale> -t "mdgb/+/forecast" -v
```

```json
{"v": 1, "node_id": "nodo01", "type": "forecast", "ts": 1791820800.0, "from": "model_and_counts",
 "now": {"ped_in": {"mean": 234.5, "low": 206.6, "high": 263.2}, "ped_out": {"mean": 117.8, "low": 101.8, "high": 134.2},
         "cyclist": {"mean": 2.8, "low": 1.7, "high": 3.9}, "vehicles": {"mean": 60.7, "low": 49.8, "high": 72.2}},
 "hours": [{"t0": 1791824400, "ped_in": 173.5, "ped_out": 80.1, "cyclist": 1.8, "vehicles": 44.5}, "... 24 ore"],
 "anomaly": {"ratio": 1.24, "measured": 360, "expected": 290, "level": "normal"},
 "model": {"trained_on": "simulated"}}
```

```json
{"v": 1, "node_id": "nodo01", "type": "analytics", "ts": 1791820800.0,
 "traffic": {"last_hour": {"ped_in": 240, "ped_out": 120, "cyclist": 0, "vehicles": 60, "animals": 0},
             "hourly": ["... 24 ore, come in /api/v1/metrics"], "peak_hour": {"t0": 1791817200, "t1": 1791820800, "pedestrians": 360},
             "pedestrians_per_hour": 360.0, "share_in": 0.67, "coverage_24h": 0.062, "provisional_share": 0.0},
 "safety": {"pedestrian_crossings": 0, "vulnerable": 0, "vehicles_met": 0, "yield_rate": null, "near_miss": 0, "incidents": 0},
 "estimate_check": {"windows": 48, "window_s": 60, "mean_count": 6.0, "mae": 0.15, "mae_persistence": 0.0, "mae_model": 4.89, "bias": -0.025}}
```

- `anomaly.level`: `normal`, `high` o `low`, cioè l'ultima ora rispetto al livello abituale di quell'attraversamento;
  `null` se le persone attese sono troppo poche per dirlo.
- Nella demo il broker è quello dell'app, aperto alla rete locale senza password: chiunque sulla rete può leggere
  questi argomenti. In produzione servono utenti e permessi sul broker (per esempio un utente per cliente, con
  accesso in sola lettura agli argomenti dei suoi nodi).

## Limiti e cose da decidere

- **Modello addestrato su dati simulati**: stime e previsioni sono indicative, e ogni risposta lo dice (`notice_model`,
  `model.trained_on`). I conteggi misurati (`last_window`, `history`, `metrics.traffic`) sono invece reali.
- Storico fino a 24 ore; per periodi più lunghi serve un archivio degli aggregati.
- Zone solo circolari o per elenco di nodi; niente poligoni.
- HTTPS, utenti MQTT, prezzi e condizioni d'uso per i clienti non sono definiti: sono decisioni del team.
