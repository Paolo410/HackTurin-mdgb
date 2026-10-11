# ai/forecast/ — expected flow at the crossing

> English translation of [`ai/forecast/README.md`](../../../../ai/forecast/README.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

**Owner:** Paolo Malugani (data scientist). It is used by the central office ([`app/`](../../app/README.md), owner
Lorenzo), which shows it in two places: the **halos** around the cameras on the map and the **Flusso atteso** (expected
flow) box in the detail of every camera. Specification: `PROMPT_SMART_CROSSING.md` §5.3.

## What it does

For every camera on the map it estimates how many **pedestrians in, pedestrians out, cyclists and vehicles** pass per
hour, now and in each of the next 24 hours. Four steps:

1. **Model.** A gradient boosting (one per class, Poisson loss) turns calendar and context of the crossing into an
   expected count per 15-minute window.
2. **Calibration.** The history of the node tells how much that crossing deviates from what the context predicts (one
   factor per class, between 0.05 and 20, which stays close to 1 while the counts are few).
3. **Fusion.** The last windows counted by the node correct the current estimate (Gamma-Poisson: the model weighs as
   much as 10 expected passages, a window 30 minutes old weighs half). How far back to look depends on how much there
   is to count: windows are added, from the most recent, until 80 passages are expected. A crowded crossing follows the
   last window, a quiet one averages many. If the counts contradict the model (ten times the expected people) the model
   loses weight at once, instead of holding the estimate back for an hour.
4. **Next hours.** The forecast starts from the current estimate and goes back to the calibrated model: whatever is
   unusual now (a crowd, an empty street) halves every hour.

A camera that sends no data (never connected, off, network down) still has the estimate of the model alone. With the
counts of the last hour the central office also says whether the passage is normal, above or below the usual.

## Metrics and check of the estimate

- **Camera metrics** (`analytics.py`), over the last 24 hours: counts of the last hour, of today and hour by hour (with
  the share of each hour really measured), peak hour, share of pedestrians in one direction; give way, near misses per
  1000 crossings, vulnerable pedestrians, incidents by type.
- **Check of the estimate** (`service.quality`): every window already counted is estimated with only the data
  available before it started, and the mean error (pedestrians per window) is compared with two references: repeating
  the last count, and the model alone without the camera. At least about twenty windows are needed.

What the check showed, on invented counts (Poisson around a known rhythm):

| Situation | Mean per window | Estimate | Repeat the last | Model only |
|---|---|---|---|---|
| Crowded, 15-min windows, model rhythm | 90.5 | 15.1 | 13.9 | 40.6 |
| Crowded, 15 min, rhythm one hour late | 79.1 | 15.4 | 13.0 | 37.5 |
| Crowded, 15 min, flat counts day and night | 128.0 | 12.9 | 13.0 | 78.2 |
| Crowded, 1-min windows | 11.4 | 3.3 | 3.9 | 5.6 |
| Quiet, 15 min | 4.1 | 1.9 | 2.6 | 3.1 |

Where the passages are many the estimate is worth as much as repeating the last count (slightly worse); where they are
few it is better. The first version averaged two hours of windows even where the last one was enough, and on high
counts it was wrong by more than double: the check was born for this, and now it is visible in the dashboard and in the
API for every camera.

Metrics, estimates and forecasts leave the central office on MQTT and with a key-based API for customers:
[`docs/DATA_API.md`](../../docs/DATA_API.md).

## In the central office

- **Slider above the map** ("Affluenza pedoni attesa", expected pedestrian turnout): from now to the next 24 hours,
  one hour per step.
- **Halo** around every camera: more pedestrians expected in the chosen hour, larger and fuller halo (the area grows in
  proportion to the flow, up to 600 pedestrians per hour). The number is written under the camera; the legend is on the
  map. The colour of the dot stays the one of the node state.
- **"Flusso atteso" box**: the four numbers of the chosen hour, the chart of the pedestrians expected per hour for the
  next 24 hours (hovering shows the values, a click chooses the hour), the hourly table and the sources used.

## Limits, to say in the pitch

- **The training history is simulated** (`simulate.py`): at the hackathon there are no historical counts. The numbers
  show the method, not real measures. With the real aggregates in the central office database it is retrained on those.
- Neither Google Maps nor the ESA satellites count pedestrians: they give the **context** (what is around, what the
  weather is like). The satellite has 10 m pixels and does not see people.
- The **direction** (in/out) depends on how the camera is mounted: the model starts from an hourly profile, the real
  split comes only from the counts of the node.
- The Google sources are written from the official documentation but **not yet tested with a real key**.
- The weather forecast covers 30 hours; Google traffic is valid only for the current hour.

## Sources

Only the coordinates of the camera are sent to the external sources. The answers stay in a disk cache
(`forecast-context.json` in the settings folder of the app) and are refreshed in the background, one camera at a time:
without Internet the model uses the last good answer, and without any source it uses only the calendar.

| Source | What it gives | Key | Refresh |
|---|---|---|---|
| [OpenStreetMap](https://wiki.openstreetmap.org/wiki/Overpass_API) | bars, shops, stops, schools, leisure places within 300 m; road class | no | 30 days |
| [ESA WorldCover](https://registry.opendata.aws/esa-worldcover-vito/) 10 m, 2021 | share of built-up, green and water within 300 m | no | 1 year |
| [Open-Meteo](https://open-meteo.com/en/docs) | temperature and rain of the next 30 hours | no | 30 minutes |
| [Google Places](https://developers.google.com/maps/documentation/places/web-service/nearby-search) | reviews and opening hours of the 20 best-known places per category | yes | 30 days |
| [Google Routes](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRoutes) | travel time with traffic divided by the one without | yes | 30 minutes |
| Node (contract C4, `agg`) | measured counts and temperature | — | every window |

OpenStreetMap is queried with Overpass, which counts on the server. The public Overpass servers are often overloaded
(on 11/10/2026 they did not answer): if the request fails, the same counts are computed here from the raw data of the
[official API](https://wiki.openstreetmap.org/wiki/API_v0.6) (1–2 MB per block, about one second).

ESA WorldCover is a public file of 36000×36000 pixels for every 3° tile: `sources.py` downloads only the header and the
inner tiles around the point (partial HTTP requests), without geographic libraries.

### Google Maps key (optional)

Without a key the model works with the three free sources. With the key it adds real opening hours, reviews and
traffic.

1. [console.cloud.google.com](https://console.cloud.google.com) → new project.
2. Enable billing: Google asks for a card even to stay within the
   [monthly free quota](https://developers.google.com/maps/billing-and-pricing/pricing).
3. "APIs & Services" → enable **Places API (New)** and **Routes API**.
4. "Credentials" → "Create credentials" → "API key"; restrict it to these two APIs.
5. In the app: **Impostazioni** (settings) button → `GOOGLE_MAPS_API_KEY=...` → close and reopen.

Consumption, for every camera on the map and only with the app open: 5 Places requests per month, one Routes request
every 30 minutes. The same key also turns on the Google map in the dashboard, if it has "Maps JavaScript API" enabled;
otherwise the map stays the one without a key.

## How to try it

With the central office app, from source (Mac or Windows):

```bash
pip install -r app/desktop/requirements.txt
python app/desktop/centrale_app.py
```

Above the map the "Affluenza pedoni attesa" slider appears and around the camera the halo with the number of
pedestrians per hour: moving the slider the halo changes. Click on the camera: under "Traffico" (traffic) there is
**Flusso atteso**. Usually within half a minute the labels at the bottom show the sources that arrived (on 11/10/2026
for `nodo01`, corso Castelfidardo corner corso Einaudi: 10 bars, 9 shops, 18 stops; ESA WorldCover 87% built-up).
Without a connected node the line says "Solo modello" (model only).

Whoever had already opened the app has the old `nodes.json` in the settings (camera in piazza San Carlo): at the first
start it is replaced with the new one, unless it was edited by hand.

To see the correction with the counts a node is needed. Without a board, with the app open, from the repo folder (it is
the simulated node of [`app/README.md`](../../app/README.md#test-on-the-pc-without-a-board-developers-only), with
aggregates every minute instead of every 15):

```bash
python -m comms.tools.c3_sim --rate 2 --duration 600 --dir /tmp/c3 &
MQTT_HOST=127.0.0.1 NODE_ID=nodo01 BACKUP_LINK=none AGG_PERIOD_S=60 MDGB_C3_DIR=/tmp/c3 DB_PATH=/tmp/nodo01.db python comms/node/main.py
```

After two or three minutes the line becomes "Stima del modello corretta con i conteggi della camera" (model estimate
corrected with the camera counts) and the numbers follow those of the node. I did not run this test with the simulated
node: here the box was tested by writing the aggregates directly into the central office database.

The packaged app (`build_mac.sh`, `build_windows.ps1`) contains the model: the self-test of the build also checks that
`/api/forecast/nodo01` answers.

Tests, without network (80 for the model, 29 for the central office):

```bash
cd ai && python -m pytest tests/test_forecast.py tests/test_forecast_sources.py tests/test_forecast_service.py tests/test_forecast_analytics.py -q
python -m pytest comms/tests/test_dashboard.py comms/tests/test_customers.py -q     # from the root
```

| File | What it checks |
|---|---|
| `ai/tests/test_forecast.py` | the main path: model, features, fusion, sources, cache, service |
| `ai/tests/test_forecast_sources.py` | the real HTTP exchange (server on the test PC), the edge cases of ESA WorldCover and OpenStreetMap, the requests to Google, the cache when a source falls or several cameras refresh together |
| `ai/tests/test_forecast_service.py` | calendar and holidays, reading of the trees, intervals, hourly forecast, anomalies, simulator and training; and that the runtime uses only the standard library, is Python 3.9 and is all in the app package |
| `ai/tests/test_forecast_analytics.py` | traffic and safety metrics, current estimate, check of the estimate on the following counts |
| `comms/tests/test_dashboard.py` | `/api/flow` and `/api/forecast` from the node aggregates, missing model, app self-test, consistency of the page (ids, colours, called addresses) |
| `comms/tests/test_customers.py` | keys (fingerprint, expiry, revocation), zones, customer API (permissions, request limit, CSV, zone without cameras), messages on MQTT |

The tests that train a model skip themselves where numpy and scikit-learn are missing (for example in the app build).
The JavaScript part of the page (halos, slider, chart) has no automatic tests: it was tested by hand in the browser.

## Retraining

```bash
pip install -r ai/forecast/requirements.txt
cd ai && python -m forecast.train                          # about 15 s, rewrites forecast/model.json
```

`train.py` simulates 240 crossings for 21 days, trains on 180 and measures on the other 60, never seen. Then it exports
the trees into `model.json` and checks that the pure-Python reader (`model.py`) gives the same numbers as scikit-learn
(maximum difference 1.2e-6 over 2000 rows): if they do not match it does not write the file.

Results on the 60 test crossings, per 15-minute window, **on simulated data**. The comparison is with the mean profile
per quarter hour of the week, the same for all the crossings:

| Class | Mean | Mean error, model | Mean error, profile | Deviance explained, model | Deviance explained, profile |
|---|---|---|---|---|---|
| Pedestrians in | 3.78 | 2.45 | 3.30 | 56% | 31% |
| Pedestrians out | 4.12 | 2.46 | 3.44 | 60% | 37% |
| Cyclists | 0.41 | 0.46 | 0.47 | 31% | 28% |
| Vehicles | 19.46 | 9.22 | 15.95 | 73% | 35% |

Cyclists are too few per window for the context to help. The error remaining on the pedestrians comes largely from
what no source sees (in the simulator `site_effect` and `in_bias`): it is the part that the counts of the node correct.

## Files

| File | What it does | Dependencies |
|---|---|---|
| `features.py` | the 17 variables of the model, calendar and Italian holidays | standard library |
| `sources.py` | the five external sources | standard library |
| `context.py` | disk cache of the context, refreshed in the background | standard library |
| `model.py` | reads `model.json` and computes the estimate | standard library |
| `fusion.py` | calibration and fusion with the counts of the node | standard library |
| `analytics.py` | traffic and safety metrics of the last 24 hours | standard library |
| `service.py` | `Forecaster.forecast(camera, windows)`: current estimate, next 24 hours, check of the estimate | standard library |
| `simulate.py`, `train.py` | simulated history and training | numpy, scikit-learn |
| `model.json` | the trained trees (214 KB of text) | — |

The runtime modules are written for Python 3.9 or later, like the app; tested on 3.12. Training tested on 3.12.

## To do

- Test the two Google sources with a real key.
- Retrain on real counts (history of the central office aggregates, or public counters of other cities).
- Opening hours from OpenStreetMap, to have that variable even without a key.
