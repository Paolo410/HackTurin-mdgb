# Data out of the central office: customer API and MQTT

> English translation of [`docs/DATA_API.md`](../../DATA_API.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

Written by Paolo (data scientist) together with the code in `app/customers.py`, `app/publisher.py` and `ai/forecast/`.
**To show Lorenzo**: they are new interfaces, they do not change the C1–C5 contracts of [`CONTRACTS.md`](CONTRACTS.md);
if he approves them, a reference to this file must be added there.

The central office receives from the nodes only anonymous counts (contract C4). With those it computes metrics and
forecasts ([`ai/forecast/`](../ai/forecast/README.md)) and makes them available in two ways:

| For whom | How | What |
|---|---|---|
| Customers (a shop, the Municipality) | HTTP with API key, `GET /api/v1/...` | real-time and forecast data of the cameras in **their zone** |
| Other systems on the same network | MQTT, `mdgb/<node>/forecast` and `mdgb/<node>/analytics` | estimate, forecast and metrics of every camera |

Images, single events or identifiers of people never leave: only counts per crossing.

## API keys

A key belongs to a customer and is valid for a **zone**: a circle on the map (centre and radius, from 50 m to 20 km)
or a list of nodes. With the key one reads the data of the cameras that are in the zone; if there are none yet, the
answers say `"available": false` and the data appear by themselves when a camera is installed there.

- **From the dashboard** (only on the central office PC): "Dati per i clienti" (data for customers) card at the bottom
  of the page. A camera is chosen on the map, the customer name, radius and duration are typed, and the key appears
  only once.
- **From the terminal**, even with the app open:

```bash
python app/customers.py create --name "Bar Sport" --lat 45.0614 --lon 7.6581 --radius 400 --days 30
python app/customers.py create --name "Comune di Torino" --nodes nodo01,nodo02
python app/customers.py list
python app/customers.py revoke 1a89b548
```

  With the packaged app the database is `central.db` in the settings folder: `--db "<folder>/central.db"`.

What to know:

- The key has the form `mdgb_<id>_<secret>`. Only its fingerprint (SHA-256) stays in the database: whoever reads the
  database cannot rebuild it, and if the customer loses it another one is created.
- Data types per key: `realtime` (counts, history, metrics) and `forecast` (forecasts). Both by default; from the
  terminal `--scopes forecast` gives only one.
- Optional expiry, immediate revocation.
- At most 120 requests per minute per key.
- Every request served is counted per key, day and data type (table `api_usage`): it is the basis for measuring the
  usage and, one day, for charging for it.
- Keys are created, listed and revoked only from the central office PC (`/api/keys` answers 403 to anybody else), even
  when the dashboard is open to the local network.

## Customer API (version 1)

Address: `http://<central office PC>:8080/api/v1/`. By default the central office listens only on its own PC; to make
it reachable from the network `WEB_HOST=0.0.0.0` is needed in the settings. **Outside a trusted network it must be put
behind HTTPS** (a proxy with a certificate): the key travels in the header and over plain HTTP it can be read.

Two warnings for whoever exposes it:

- The proxy must forward **only `/api/v1/`**. Key management (`/api/keys`) recognises the central office PC from the
  address of the caller: behind a proxy on the same machine every request looks local.
- The rest of the dashboard (`/`, `/api/state`, `/api/flow`) has no keys: it is meant for whoever supervises the
  crossings, on the central office network.

The key goes in a header, never in the address:

```bash
curl -H "X-API-Key: mdgb_1a89b548_..." http://localhost:8080/api/v1/forecast
curl -H "Authorization: Bearer mdgb_1a89b548_..." "http://localhost:8080/api/v1/history?hours=6&format=csv" -o counts.csv
```

| Address | Data type | What it returns |
|---|---|---|
| `GET /api/v1/` | no key | description of the API |
| `GET /api/v1/zone` | any | the zone of the key, the cameras it contains, the expiry |
| `GET /api/v1/realtime` | `realtime` | per camera: last counted window, last hour, current estimate per hour with interval; zone total |
| `GET /api/v1/forecast?hours=24` | `forecast` | per camera and for the zone: hour-by-hour forecast (1–24 hours); `&format=csv` |
| `GET /api/v1/history?hours=24` | `realtime` | per camera: the counted windows (1–24 hours); `&format=csv` |
| `GET /api/v1/metrics` | `realtime` | per camera: traffic of the last 24 hours, safety, check of the estimate |

In every answer: `zone`, `available` (there are cameras in the zone), `generated_at` (UTC epoch seconds) and
`generated_at_iso`. Times are always in UTC epoch seconds, with the ISO form next to them (`t0_iso`). The counts are
`ped_in`, `ped_out` (pedestrians in the two directions), `cyclist`, `vehicles`.

Errors, always `{"error": "..."}`:

| Code | When |
|---|---|
| 401 | key missing, malformed, unknown, expired or revoked |
| 403 | the key does not include that data type |
| 429 | more than 120 requests in a minute (`Retry-After: 60`) |

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

- `last_window`, `last_hour`: counts measured by the camera; `null` if it has not sent data yet.
  `provisional: true` = window arrived over the backup channel (Bluetooth), replaced by the exact one as soon as the
  network returns.
- `last_data_s`: seconds since the last window received. If it grows, the camera is not counting.
- `estimate_per_hour`: estimate of the current flow, in passages per hour, with an 80% interval.
  `estimate_from`: `model_and_counts` if corrected with the recent counts, `model_only` if the camera is silent.
- `notice_model` (in Italian in the answer): "estimates and forecasts come from a model trained on a simulated history ...".

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

One row per clock hour, from the next one onwards: passages expected in that hour. `zone_hours` is the sum of the
cameras of the zone. In CSV: `camera,name,t0,t0_iso,t1,ped_in,ped_out,cyclist,vehicles`.

### `/api/v1/metrics`

Per camera, `metrics.traffic` (last hour, today, last 24 hours, hour by hour with `coverage` = share of the hour
really measured, peak hour, share of pedestrians in one direction), `metrics.safety` (crossings, vulnerable
pedestrians, vehicles that gave way, near misses per 1000 crossings, incidents by type) and `estimate_check`:

```json
{"windows": 48, "window_s": 60, "mean_count": 6.0, "mae": 0.15, "mae_persistence": 0.0, "mae_model": 4.89, "bias": -0.025}
```

Every window already counted was estimated with only the data available before it started. `mae` is the mean error of
the estimate in pedestrians per window; `mae_persistence` the one obtained by repeating the last count; `mae_model` the
one of the model alone, without the camera. `null` while the counted windows are fewer than twenty.

## MQTT

Every 30 seconds (`ANALYTICS_PERIOD_S` in the settings; 0 = off) the central office publishes on its own broker, for
every camera, two JSON messages with QoS 1 and **retained**: whoever connects receives the last value at once.

| Topic | Content |
|---|---|
| `mdgb/<node>/forecast` | current estimate and forecast of the next 24 hours, in passages per hour |
| `mdgb/<node>/analytics` | metrics of the last 24 hours and check of the estimate (as `/api/v1/metrics`) |

The prefix `mdgb` follows `TOPIC_PREFIX`. They are topics different from those the nodes publish and the central office
listens to (`events`, `agg`, `hb`, `backup`): they never re-enter the ingest.

```bash
mosquitto_sub -h <central office PC> -t "mdgb/+/forecast" -v
```

```json
{"v": 1, "node_id": "nodo01", "type": "forecast", "ts": 1791820800.0, "from": "model_and_counts",
 "now": {"ped_in": {"mean": 234.5, "low": 206.6, "high": 263.2}, "ped_out": {"mean": 117.8, "low": 101.8, "high": 134.2},
         "cyclist": {"mean": 2.8, "low": 1.7, "high": 3.9}, "vehicles": {"mean": 60.7, "low": 49.8, "high": 72.2}},
 "hours": [{"t0": 1791824400, "ped_in": 173.5, "ped_out": 80.1, "cyclist": 1.8, "vehicles": 44.5}, "... 24 hours"],
 "anomaly": {"ratio": 1.24, "measured": 360, "expected": 290, "level": "normal"},
 "model": {"trained_on": "simulated"}}
```

```json
{"v": 1, "node_id": "nodo01", "type": "analytics", "ts": 1791820800.0,
 "traffic": {"last_hour": {"ped_in": 240, "ped_out": 120, "cyclist": 0, "vehicles": 60, "animals": 0},
             "hourly": ["... 24 hours, as in /api/v1/metrics"], "peak_hour": {"t0": 1791817200, "t1": 1791820800, "pedestrians": 360},
             "pedestrians_per_hour": 360.0, "share_in": 0.67, "coverage_24h": 0.062, "provisional_share": 0.0},
 "safety": {"pedestrian_crossings": 0, "vulnerable": 0, "vehicles_met": 0, "yield_rate": null, "near_miss": 0, "incidents": 0},
 "estimate_check": {"windows": 48, "window_s": 60, "mean_count": 6.0, "mae": 0.15, "mae_persistence": 0.0, "mae_model": 4.89, "bias": -0.025}}
```

- `anomaly.level`: `normal`, `high` or `low`, i.e. the last hour compared with the usual level of that crossing; `null`
  if the expected people are too few to say.
- In the demo the broker is the app's, open to the local network without password: anybody on the network can read
  these topics. In production users and permissions on the broker are needed (for example one user per customer, with
  read-only access to the topics of their nodes).

## Limits and things to decide

- **Model trained on simulated data**: estimates and forecasts are indicative, and every answer says so
  (`notice_model`, `model.trained_on`). The measured counts (`last_window`, `history`, `metrics.traffic`) are instead
  real.
- History up to 24 hours; for longer periods an archive of the aggregates is needed.
- Zones only circular or by list of nodes; no polygons.
- HTTPS, MQTT users, prices and terms of use for customers are not defined: they are team decisions.
