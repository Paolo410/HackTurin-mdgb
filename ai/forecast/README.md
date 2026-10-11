# ai/forecast/ — flusso atteso all'attraversamento

**Owner:** Paolo Malugani (data scientist). Lo usa la centrale ([`app/`](../../app/README.md), owner Lorenzo), che mostra
il riquadro **Flusso atteso** nel dettaglio di ogni camera. Specifica: `PROMPT_SMART_CROSSING.md` §5.3.

## Cosa fa

Per ogni camera della mappa stima quanti **pedoni in, pedoni out, ciclisti e veicoli** passano adesso e nelle
prossime 3 ore, per finestre di 15 minuti. Tre passi:

1. **Modello.** Un gradient boosting (uno per classe, loss di Poisson) trasforma calendario e contesto
   dell'attraversamento in un conteggio atteso.
2. **Calibrazione.** Lo storico del nodo dice quanto quell'attraversamento si scosta da ciò che il contesto fa
   prevedere (un fattore per classe, tra 0,1 e 10, che resta vicino a 1 finché i conteggi sono pochi).
3. **Fusione.** Le ultime finestre contate dal nodo correggono la stima di adesso (Gamma-Poisson: il modello pesa
   quanto 15 minuti di conteggi, una finestra vecchia di 30 minuti pesa la metà).

Una camera che non manda dati (mai collegata, spenta, rete giù) ha comunque la stima del solo modello. Con i
conteggi dell'ultima ora la centrale dice anche se il passaggio è nella norma, sopra o sotto il solito.

## Limiti, da dire nel pitch

- **Lo storico di addestramento è simulato** (`simulate.py`): all'hackathon non ci sono conteggi storici. I numeri
  mostrano il metodo, non misure reali. Con gli aggregati veri nel database della centrale si riaddestra su quelli.
- Né Google Maps né i satelliti ESA contano i pedoni: danno il **contesto** (cosa c'è intorno, che tempo fa). Il
  satellite ha pixel di 10 m e non vede le persone.
- La **direzione** (in/out) dipende da come è montata la camera: il modello parte da un profilo orario, la
  ripartizione vera arriva solo dai conteggi del nodo.
- Le fonti Google sono scritte dalla documentazione ufficiale ma **non ancora provate con una chiave vera**.

## Fonti

Alle fonti esterne si mandano solo le coordinate della camera. Le risposte restano in una cache su disco
(`forecast-context.json` nella cartella delle impostazioni dell'app) e si aggiornano in background: senza Internet il
modello usa l'ultima risposta buona, e senza nessuna fonte usa solo il calendario.

| Fonte | Cosa dà | Chiave | Aggiornamento |
|---|---|---|---|
| [OpenStreetMap](https://wiki.openstreetmap.org/wiki/Overpass_API) (Overpass) | locali, negozi, fermate, scuole, luoghi di svago entro 300 m; classe della strada | no | 30 giorni |
| [ESA WorldCover](https://registry.opendata.aws/esa-worldcover-vito/) 10 m, 2021 | quota di costruito, verde e acqua entro 300 m | no | 1 anno |
| [Open-Meteo](https://open-meteo.com/en/docs) | temperatura e pioggia, ora e prossime ore | no | 30 minuti |
| [Google Places](https://developers.google.com/maps/documentation/places/web-service/nearby-search) | recensioni e orari di apertura dei 20 luoghi più noti per categoria | sì | 30 giorni |
| [Google Routes](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes) | tempo di percorrenza con traffico diviso quello senza | sì | 30 minuti |
| Nodo (contratto C4, `agg`) | conteggi e temperatura misurati | — | ogni finestra |

ESA WorldCover è un file pubblico di 36000×36000 pixel per ogni riquadro di 3°: `sources.py` scarica solo
l'intestazione e i riquadri interni intorno al punto (richieste HTTP parziali), senza librerie geografiche.
Overpass è un servizio condiviso e a volte lento (fino a 45 s): la richiesta parte una volta al mese per camera.

### Chiave di Google Maps (facoltativa)

Senza chiave il modello funziona con le tre fonti gratuite. Con la chiave aggiunge orari reali, recensioni e traffico.

1. [console.cloud.google.com](https://console.cloud.google.com) → nuovo progetto.
2. Attiva la fatturazione: Google chiede una carta anche per restare nella
   [quota gratuita mensile](https://developers.google.com/maps/billing-and-pricing/pricing).
3. "API e servizi" → abilita **Places API (New)** e **Routes API**.
4. "Credenziali" → "Crea credenziali" → "Chiave API"; limitala a queste due API.
5. Nell'app: pulsante **Impostazioni** → `GOOGLE_MAPS_API_KEY=...` → chiudi e riapri.

Consumo: 5 richieste Places per camera al mese, una richiesta Routes ogni 30 minuti per la camera che si sta guardando.
La stessa chiave accende anche la mappa di Google nella dashboard, se ha "Maps JavaScript API" abilitata; altrimenti
la mappa resta quella senza chiave.

## Come si prova

Con l'app della centrale, da sorgente (Mac o Windows):

```bash
pip install -r app/desktop/requirements.txt
python app/desktop/centrale_app.py
```

Clic sulla camera: sotto "Traffico" compare **Flusso atteso**. Di solito entro mezzo minuto le etichette in basso
mostrano le fonti arrivate (l'11/10/2026 per `nodo01`: 76 locali, 178 negozi, 14 fermate; ESA WorldCover 98% costruito). Senza nodo collegato
la riga dice "Solo modello".

Per vedere la correzione con i conteggi serve un nodo. Senza scheda, con l'app aperta, dalla cartella del repo (è il
nodo simulato di [`app/README.md`](../../app/README.md#prova-sul-pc-senza-scheda-solo-sviluppatori), con gli aggregati
ogni minuto invece che ogni 15):

```bash
python -m comms.tools.c3_sim --rate 2 --duration 600 --dir /tmp/c3 &
MQTT_HOST=127.0.0.1 NODE_ID=nodo01 BACKUP_LINK=none AGG_PERIOD_S=60 MDGB_C3_DIR=/tmp/c3 DB_PATH=/tmp/nodo01.db python comms/node/main.py
```

Dopo due o tre minuti la riga diventa "Stima del modello corretta con i conteggi della camera" e i numeri seguono
quelli del nodo. Questa prova con il nodo simulato non l'ho eseguita: qui il riquadro è stato provato scrivendo gli
aggregati direttamente nel database della centrale.

L'app impacchettata (`build_mac.sh`, `build_windows.ps1`) contiene il modello: l'autotest della build controlla anche
che `/api/forecast/nodo01` risponda.

Test, senza rete:

```bash
cd ai && python -m pytest tests/test_forecast.py -q        # 20 test
python -m pytest comms/tests/test_dashboard.py -q          # dalla root: endpoint della centrale
```

## Riaddestrare

```bash
pip install -r ai/forecast/requirements.txt
cd ai && python -m forecast.train                          # circa 15 s, riscrive forecast/model.json
```

`train.py` simula 240 attraversamenti per 21 giorni, addestra su 180 e misura sugli altri 60, mai visti. Poi esporta
gli alberi in `model.json` e controlla che il lettore in Python puro (`model.py`) dia gli stessi numeri di scikit-learn
(differenza massima 1,2e-6 su 2000 righe): se non coincidono non scrive il file.

Risultati sui 60 attraversamenti di prova, per finestra di 15 minuti, **su dati simulati**. Il confronto è con il
profilo medio per quarto d'ora della settimana, uguale per tutti gli attraversamenti:

| Classe | Media | Errore medio, modello | Errore medio, profilo | Devianza spiegata, modello | Devianza spiegata, profilo |
|---|---|---|---|---|---|
| Pedoni in | 3,78 | 2,45 | 3,30 | 56% | 31% |
| Pedoni out | 4,12 | 2,46 | 3,44 | 60% | 37% |
| Ciclisti | 0,41 | 0,46 | 0,47 | 31% | 28% |
| Veicoli | 19,46 | 9,22 | 15,95 | 73% | 35% |

I ciclisti sono troppo pochi per finestra perché il contesto aiuti. L'errore che resta sui pedoni viene in gran parte
da ciò che nessuna fonte vede (nel simulatore `site_effect` e `in_bias`): è la parte che i conteggi del nodo correggono.

## File

| File | Cosa fa | Dipendenze |
|---|---|---|
| `features.py` | le 17 variabili del modello, calendario e festività italiane | libreria standard |
| `sources.py` | le cinque fonti esterne | libreria standard |
| `context.py` | cache su disco del contesto, aggiornata in background | libreria standard |
| `model.py` | legge `model.json` e calcola la stima | libreria standard |
| `fusion.py` | calibrazione e fusione con i conteggi del nodo | libreria standard |
| `service.py` | `Forecaster.forecast(camera, finestre)`: quello che la dashboard mostra | libreria standard |
| `simulate.py`, `train.py` | storico simulato e addestramento | numpy, scikit-learn |
| `model.json` | gli alberi addestrati (214 KB di testo) | — |

I moduli di runtime sono scritti per Python 3.9 o superiore, come l'app; provati su 3.12. Addestramento provato su 3.12.

## Da fare

- Provare le due fonti Google con una chiave vera.
- Riaddestrare su conteggi reali (storico degli aggregati della centrale, o contatori pubblici di altre città).
- Orari di apertura da OpenStreetMap, per avere quella variabile anche senza chiave.
