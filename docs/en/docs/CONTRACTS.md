# Contracts between the MDGB modules — v1

> English translation of [`docs/CONTRACTS.md`](../../CONTRACTS.md), from `main` at `1f9a131` (11 October 2026). The Italian original is the reference: if the two differ, the original wins.

Owner: **Lorenzo Dragoni** (communication engineer). Pinout section: **Kuzey Bicher** (electronics).
Basis: `PROMPT_SMART_CROSSING.md` §4, corrected with the decisions of `comms/DECISIONS.md`.

Rules:
- every JSON message has `"v"` (version of its contract); this file is v1;
- new **optional** fields can be added without changing the version: readers ignore the fields they do not know;
- renaming, removing or changing the meaning of a field = new version, proposed by the owner and communicated to the team;
- times in UTC epoch seconds (`ts`, float) except where `t_ms` is stated; texts in UTF-8; JSON on a single line.

Entries marked **[to confirm: X]** are my proposals on points the specification leaves open: X must say ok.

## Map

| ID | From → To | Transport | Produces | Consumes |
|---|---|---|---|---|
| C1 | AI → firmware: command | serial 115200 or Bridge, through `Actuator` | Paolo (`rules.py`) | Salvatore |
| C2 | AI → firmware: heartbeat | as C1 | Paolo (`app.py`) | Salvatore |
| C3 | AI → comms/app: events | JSONL files | Paolo (`logger.py`) | Lorenzo |
| C4 | node → central office | MQTT 5 (broker on the central office PC in the demo) | Lorenzo (`comms/`) | Lorenzo (`app/`) |
| C4-B | node → central office, backup | BLE (demo) / LoRaWAN (production), binary | Lorenzo (`comms/`), Salvatore for the LoRa radio | Lorenzo (`app/`) |
| C5 | firmware → Linux: MCU data | serial or Bridge, JSON lines | Salvatore | Paolo, Lorenzo |
| Bridge | Linux ↔ MCU RPC functions on the UNO Q | Arduino_RouterBridge | Salvatore (MCU), Lorenzo (Linux) | — |

Processes on the UNO Q **[to confirm: Paolo]**: `ai` (vision, rules, `Actuator`) and `comms` (uplink, Store & Forward,
backup) run separately and talk only through the C3 files. If `comms` falls safety does not change; if `ai` falls the
firmware goes into fail-safe and `comms` keeps emptying the queue.

---

## C1 — AI → firmware command (unchanged from §4)

```json
{"v":1,"seq":1842,"t_ms":1739012345678,"state":"WARN_DRIVER","led":"AMBER_BLINK_2HZ","green_s":19,"req":{"ped_green_extend_s":7,"veh_red_hold":true,"flash":false},"lcd":"PEDONE  47 km/h","oled":"ATTENDI auto 45km/h","reason":"anziano 0.8 m/s; auto 50 km/h a 60 m; TTC 4.3 s < T_need 9.8 s"}
```

- `state` ∈ `IDLE | PRESENCE | WARN_DRIVER | WARN_PEDESTRIAN | ANIMAL_WARN | ANIMAL_ALERT | DEGRADED`
- `led` ∈ `OFF | WHITE_ON | AMBER_BLINK_2HZ | AMBER_BLINK_4HZ | RED_GROUND_BLINK | YELLOW_FAILSAFE`
- `req` = requests to the traffic-light controller (real or simulated). The firmware applies them only within its fixed
  limits (pedestrian green +15 s at most, vehicle red held 20 s at most, minimum vehicle green 8 s).
- `lcd` (drivers) and `oled` (pedestrians): texts to show. The example texts are the Italian ones shown on the device
  ("PEDONE" = pedestrian, "ATTENDI auto" = wait, car; the `reason` reads "elderly 0.8 m/s; car 50 km/h at 60 m; ...").

Transport (my additions, valid for serial and Bridge):
- one line = one JSON object, terminated by `\n` on the serial (without `\n` as a Bridge argument);
- **at most 512 bytes per line** (size of the MCU receive buffer);
- serial: 115200 baud, 8N1;
- `lcd` **[to confirm: Salvatore]**: ASCII only, at most 32 characters; the first 16 go on line 1, the following ones on line 2;
- **[to confirm: Paolo]** the AI repeats the last C1 at least every 1 s even if it does not change, so a line lost on
  the serial does not leave the firmware in an old state. The firmware treats C1 as idempotent.

## C2 — AI → firmware heartbeat (unchanged from §4)

```json
{"v":1,"hb":1843}
```

- Every 100 ms, same transport as C1.
- More than 500 ms without heartbeat: in `signalized` mode the firmware cancels all the requests and the controller goes
  back to the normal cycle; in `uncontrolled` mode it switches to `YELLOW_FAILSAFE`.

## Python interface `Actuator` (`comms/actuators.py`)

```python
class Actuator:
    def send(self, cmd: dict) -> None: ...      # C1
    def heartbeat(self, seq: int) -> None: ...  # C2
    def close(self) -> None: ...
# implementations: SimActuator, SerialActuator(port, baud=115200), BridgeActuator (UNO Q)
# factory: make_actuator(kind: "sim" | "serial" | "bridge", **kwargs) -> Actuator
```

- `send` and `heartbeat` do not block and do not raise exceptions if the link falls: `SerialActuator` reconnects by
  itself (safety is guaranteed anyway by the 500 ms timeout of the firmware). If the link is slow only the last C1 and
  the last C2 are sent (commands are states, not queues).
- If a line exceeds 512 bytes, `Actuator` shortens `reason`; if that is not enough it raises `ValueError` (programming
  error, not network error).
- The C5 lines received from the MCU are written by `Actuator` in `$MDGB_C3_DIR/mcu-*.jsonl` (same rules as C3).
  **[to confirm: Paolo]** In addition: optional `set_listener(cb: Callable[[dict], None])`, to get the C5 lines also
  inside `ai/` (for example `lamp_fault` or `tamper` → `DEGRADED`, thermal array).

## Bridge — RPC functions on the UNO Q

MessagePack-RPC through the `arduino-router` service of the board (socket `unix:///var/run/arduino-router.sock`).
- MCU side: library [Arduino_RouterBridge](https://github.com/arduino-libraries/Arduino_RouterBridge):
  `Bridge.begin()`, `Bridge.provide(...)`, `Bridge.provide_safe(...)`, `Bridge.call(...)`, `Bridge.notify(...)`.
- Linux side: official library [arduino-router-bridge](https://github.com/arduino/arduino-router-bridge-py)
  (`pip install arduino-router-bridge`, in `comms/requirements.txt`), the same that App Lab uses inside
  `arduino.app_utils.Bridge`: it also works from a normal venv or a systemd service, without App Lab. It is used by
  `BridgeActuator` in `comms/actuators.py`.
- Several Linux processes can use the router together (the vision and, in production, the node for LoRa): every
  function exposed with `provide` belongs to a single process.

**[to confirm: Salvatore]** (Linux side already done and tested with the official library)

| Function | Who exposes it | Arguments | Returns | Use |
|---|---|---|---|---|
| `mdgb_line` | MCU, with `Bridge.provide_safe` (runs in `loop()`, no race with LEDs and controller) | `String`: one C1 or C2 line | `bool` (true = valid line) | C1, C2. Same parser as the serial |
| `mcu_event` | Linux, with `Bridge.provide` | `String`: one C5 line | — (the MCU uses `Bridge.notify`) | C5 |
| `lora_send` | MCU | `int fport`, `String hex` (C4-B body) | `bool` (true = queued) | production only |
| `lora_joined` | MCU | — | `bool` | production only |

Warning from the library: do not call `Bridge.call` inside a function registered with `provide` (risk of deadlock).
Production watchdog: if the MCU does not receive C2 for 5 min, it sends `DEAD` over LoRa (C4-B type 9).

## C5 — MCU data → Linux [to confirm: Salvatore, Paolo]

Same transport as C1, in the opposite direction. On the serial the lines starting with `{` are C5; the others are debug
logs and are ignored.

```json
{"v":1,"src":"mcu","type":"env","t_c":14.2,"rh":81,"lux":120,"batt":87}
{"v":1,"src":"mcu","type":"tamper","code":1}
{"v":1,"src":"mcu","type":"lamp_fault","pattern":"AMBER_BLINK_2HZ","i_ma":120,"exp_ma":480}
{"v":1,"src":"mcu","type":"failsafe","reason":"hb_timeout"}
{"v":1,"src":"mcu","type":"thermal","t":[21.4,21.6,"… 64 values, 16x4 by rows"]}
```

- `env` every 10 s; `thermal` 4 times per second (for `thermal.py`); the others as soon as they happen.
- `env.batt`: battery charge in % from the LTC2941, optional (absent if not measured). Every field of `env` is optional.
- `tamper.code`: 1 = shock or tilt (IMU), 2 = case door open (micro switch), 3 = authorised opening (technician's NFC
  badge: the central office gives no alarm for the door in the following 10 min).
- `failsafe.reason`: `hb_timeout` | `lamp_fault` | `boot`.
- The MCU does not know the time: `ts` is added by Linux when it receives the line.
- `Actuator` writes to file all the C5 lines except `thermal` (too frequent: it only reaches the listener).

## C3 — AI → comms/app events

Format unchanged from §4:

```json
{"v":1,"ts":1739012345.67,"type":"crossing","track_id":12,"cls":"pedestrian","attrs":{"child":false,"slow":true,"aid":null},"dir":"in","line":"ped"}
{"v":1,"ts":1739012350.10,"type":"near_miss","a":12,"b":31,"ttc_s":0.8,"pet_s":null}
{"v":1,"ts":1739012399.00,"type":"incident","kind":"person_down","track_id":12,"zone":"carriageway"}
{"v":1,"ts":1739012400.00,"type":"status","state":"PRESENCE","fps":9.6,"lat_ms":{"detect":71,"track":3,"rules":1,"act":2},"counts":{"ped_in":14,"ped_out":11,"car_in":52}}
```

Allowed values **[to confirm: Paolo]**:
- `type` ∈ `crossing | near_miss | incident | yield | status`;
- `cls` ∈ `pedestrian | cyclist | motorcyclist | car | bus | truck | animal | bird`; for `animal` and `bird` there is also
  `"coco":"dog"` (original COCO class, §7);
- pedestrian seen only in thermal (Paolo's question 7): `"cls":"pedestrian"` with `"attrs":{"thermal_only":true}`;
- `attrs.aid` ∈ `null` (model missing) `| "normal" | "wheelchair" | "walking_aid" | "stroller"`;
- `dir` ∈ `in | out`; `line` ∈ `ped | veh`;
- `incident.kind` ∈ `person_down | collision | hard_brake | vehicle_on_crosswalk`;
- `yield` (new, needed for the yield rate of the aggregates): one line per vehicle arriving with a pedestrian in the
  waiting area, `{"v":1,"ts":…,"type":"yield","track_id":31,"yielded":true}`;
- `status` every 5 s.

Transport **[to confirm: Paolo]** (closes Paolo's question 6; the HTTP endpoint is not needed in v1):
- folder `$MDGB_C3_DIR` (default `logs/c3/` in the root of the repo, ignored by git);
- files `c3-YYYYMMDD-HHMMSS.jsonl` (UTC opening time): alphabetical order is time order;
- append only: one complete line per write, terminated by `\n`, with flush. Rotation = the file is closed and a new one
  is opened. Never rewrite or truncate a file;
- a file can be deleted only after 7 days (`comms` needs them until it has read them);
- `comms` reads the files in order and saves (file, offset) in the same SQLite commit as the outbox: no losses and no
  duplicates even if `comms` restarts. A line without a final `\n` is read only when it is complete.

---

## C4 — Node → central office (MQTT 5)

**Demo:** Mosquitto broker inside the central office app on the PC, port 1883 on the local network, without TLS or
certificates.
**Production (future):** an MQTT 5 broker in the cloud, mutual TLS on port 8883 and one X.509 certificate per node.
Topics and messages are the same in both cases.

In both cases: client ID = `node_id` (`^[a-z0-9-]{1,32}$`, e.g. `nodo07`), MQTT 5, QoS 1 everywhere,
`clean_start=false`, Session Expiry 3600 s.

### Topics

Prefix `mdgb` (configurable with `TOPIC_PREFIX`).

| Topic | From → To | Content | QoS | Retained |
|---|---|---|---|---|
| `mdgb/<node_id>/events` | node → central office | batch of events from the Store & Forward | 1 | no |
| `mdgb/<node_id>/agg` | node → central office | exact aggregate per window | 1 | no |
| `mdgb/<node_id>/hb` | node → central office | heartbeat every 10 s; Last Will on the same topic | 1 | yes |
| `mdgb/<node_id>/backup` | BLE/LoRa receiver → central office | republished C4-B messages | 1 | no |

There is no `alert` any more: alarms are events and go through the Store & Forward like all the others.

### `events`

```json
{"v":1,"node_id":"nodo07","events":[
  {"seq":805,"event_id":"nodo07-000805","ts":1739012345.67,"type":"crossing","track_id":12,"cls":"pedestrian","attrs":{"child":false,"slow":true,"aid":null},"dir":"in","line":"ped"},
  {"seq":806,"event_id":"nodo07-000806","ts":1739012350.10,"type":"near_miss","a":12,"b":31,"ttc_s":0.8,"pet_s":null}
]}
```

- Every event = the C3 line (or non-periodic C5: `tamper`, `lamp_fault`, `failsafe`) **unchanged**, plus `seq` and
  `event_id` added by `comms`.
- `seq`: integer assigned by `comms` when it writes the event to disk, persistent, never reused.
  `event_id` = `<node_id>-<seq>` with `seq` of at least 6 digits (`nodo07-000805`).
- From 1 to 50 events per message, in `seq` order. Online usually one at a time is sent; in the backfill the batch is filled.
- The central office deduplicates on `(node_id, seq)`; the gaps in `seq` are lost data.
- The C3 `status` lines and the C5 `env`/`thermal` lines do not become events: they end up in `hb` and `agg`.

### `agg`

```json
{"v":1,"node_id":"nodo07","type":"agg","t0":1739011500,"t1":1739012400,"counts":{"pedestrian":{"in":14,"out":11},"cyclist":{"in":4,"out":2},"car":{"in":52,"out":0}},"vulnerable":3,"near_miss":1,"incident":0,"yield_rate":0.42,"env":{"t_c":14.2,"rh":81,"lux":120},"queue":0}
```

- Fixed windows of 900 s (60 s in the demo), computed from the events on disk: they are exact, also those matured during
  a blackout (they are sent when the network returns).
- Key `(node_id, t0)`, without `event_id`: if it arrives twice it is overwritten. It replaces the provisional aggregate
  arrived from the backup.
- `vulnerable` = pedestrians with `child`, `slow` or `aid` other than `null`/`normal`. `yield_rate` = `null` if no vehicle.

### `hb`

```json
{"v":1,"node_id":"nodo07","type":"hb","ts":1739012400.0,"online":true,"mode":"normal","state":"PRESENCE","backup":"off","batt":null,"queue":0,"disk_free_pct":87,"fps":9.6}
```

Last Will (retained, QoS 1), published by the broker if the node disappears:
```json
{"v":1,"node_id":"nodo07","type":"hb","online":false}
```

- `mode` ∈ `normal | degraded | failsafe` (`degraded` = last C3 `status` in `DEGRADED`; `failsafe` = C5 `failsafe`).
- `backup` ∈ `off | ble | lora`: backup channel on at this moment.
- `batt` = % or `null` if not measured; `queue` = queued events not yet confirmed.

### Failover semantics (node)

- Confirmation = PUBACK with reason code < 0x80 (0x00 Success and 0x10 No matching subscribers are confirmations).
  PUBACK with reason code ≥ 0x80: the event is **not** sent and stays in the queue.
- Since `hb` leaves every 10 s with QoS 1, there are confirmations even when there are no events.
- No confirmation for 30 s → backup on, and the first packet leaves at once (`HB` and last closed `AGG`).
- MQTT keeps reconnecting and does the backfill as soon as it can.
- 60 s of stable MQTT (connected, regular confirmations, no negative PUBACK) → backup off.

---

## C4-B — Compact backup (BLE in the demo, LoRaWAN in production)

Only alarms (at once), heartbeat (every 5 min) and aggregates (every 15 min). Never the single events. Binary,
little-endian. Only while the backup is on (see failover).

Common envelope:
- **LoRaWAN**: fPort = `type`, FRMPayload = body. Wio-E5 on the UART of the MCU, EU868, OTAA, class A, ADR (AT commands
  of the tested code).
- **BLE**: non-connectable advertising, Manufacturer Specific Data with company ID `0xFFFF` (reserved for tests).
  27-byte frame = `type` (1 byte) + body, padded with zeros. AD structure: `len | 0xFF | 0xFFFF LE | frame` = 31 bytes.
- `ver` = 1 (the old 28-byte aggregate of the prototype is no longer used).

| type / fPort | Message | When | Body |
|---|---|---|---|
| 1 | `AGG` aggregate | every 15 min and when the backup turns on | 26 bytes |
| 2 | `HB` heartbeat | every 5 min and when the backup turns on | 12 bytes |
| 9 | `DEAD` | MCU watchdog, LoRa only | `0xDE 0xAD` |
| 10 | `TAMPER` tampering | at once | `ts` uint32 \| `code` uint8 (as C5) |
| 11 | `INCIDENT` | at once | `ts` uint32 \| `code` uint8: 1 person_down, 2 collision, 3 hard_brake, 4 vehicle_on_crosswalk |
| 12 | `FAULT` node faulty | at once | `ts` uint32 \| `code` uint8: 1 lamp_fault, 2 video missing, 3 lens covered, 4 glare, 5 firmware fail-safe |

Production only: one `HB` over LoRa every 6 h even with healthy MQTT, to check that the backup channel works.

### `AGG`, 26 bytes (`struct` `<BIBHHHHBBBBBbBHHB`)

| Byte | Field | Type | Notes |
|---|---|---|---|
| 0 | `ver` (4 bits) \| `ts_quality` (2 bits: 0 NTP, 1 RTC) \| `degraded` (1 bit) \| reserved (1 bit) | uint8 | |
| 1–4 | `t0` | uint32 | start of the window, epoch s |
| 5 | window length | uint8 | minutes |
| 6–7 | pedestrians `in` | uint16 | |
| 8–9 | pedestrians `out` | uint16 | |
| 10–11 | cyclists (in + out) | uint16 | |
| 12–13 | vehicles (car, motorcyclist, bus, truck; in + out) | uint16 | |
| 14 | animals | uint8 | saturated at 255 |
| 15 | vulnerable pedestrians | uint8 | saturated at 255 |
| 16 | near misses | uint8 | |
| 17 | incidents | uint8 | |
| 18 | yield rate | uint8 | 0–100 %, 255 = n/a |
| 19 | temperature | int8 | rounded °C, −128 = n/a |
| 20 | humidity | uint8 | %, 255 = n/a |
| 21–22 | light | uint16 | lux, 65535 = n/a |
| 23–24 | backlog / 10 | uint16 | queued events |
| 25 | battery | uint8 | %, 255 = n/a |

Example (t0 1739011500, 15 min, 14/11 pedestrians, 6 cyclists, 52 vehicles, 1 animal, 3 vulnerable, 1 near miss,
yield 42%, 14 °C, 81%, 120 lux, backlog 1234, battery n/a):
`10AC35A7670F0E000B0006003400010301002A0E5178007B00FF`

### `HB`, 12 bytes (`struct` `<BIBHBBH`)

| Byte | Field | Type | Notes |
|---|---|---|---|
| 0 | `ver` (4 bits) \| `mode` (2 bits: 0 normal, 1 degraded, 2 failsafe) \| `ts_quality` (2 bits) | uint8 | |
| 1–4 | `ts` | uint32 | epoch s |
| 5 | `state` | uint8 | index in C1: 0 IDLE, 1 PRESENCE, 2 WARN_DRIVER, 3 WARN_PEDESTRIAN, 4 ANIMAL_WARN, 5 ANIMAL_ALERT, 6 DEGRADED |
| 6–7 | backlog / 10 | uint16 | |
| 8 | battery | uint8 | %, 255 = n/a |
| 9 | free disk | uint8 | % |
| 10–11 | minutes without MQTT confirmations | uint16 | |

Example: `103039A767017B00FF570200`

Constraints: 26 bytes is the maximum that fits in a legacy BLE advertising, and it stays below the 51 bytes of LoRaWAN
EU868 even at SF12. With the 1% duty cycle one `AGG` every 15 min and one `HB` every 5 min are well within the limits.
On TTN the fair use of 30 s of airtime per day also applies: respected only with low SFs (ADR); not an issue with a
gateway owned by the central office.

### Receiver → central office (`mdgb/<node_id>/backup`)

```json
{"v":1,"node_id":"nodo07","via":"ble","type":1,"hex":"10AC35A7670F0E000B0006003400010301002A0E5178007B00FF","rssi":-67,"rx_at":1739012401.2}
```

- `via` ∈ `ble | lorawan`. The receiver does not decode: it forwards `type` and body, the central office decodes (a
  single decoder).
- `node_id`: for BLE from the MAC of the node (table in the configuration of the receiver, `TODO(verify)` that the BLE
  address of the UNO Q is stable); for LoRaWAN from the TTN `device_id` (= `node_id`).
- The BLE receiver forwards a frame only the first time it sees it (the beacon repeats several times per second).
- In the demo the BLE receiver is inside the central office (`app/central.py`) and writes directly into its database:
  the backup does not go through the Internet. The `backup` topic is for remote receivers (LoRaWAN gateways, distant
  BLE receivers).
- BLE: the node keeps up to three beacons on air together (instance 1 `AGG`, 2 `HB`, 3 alarms), in rotation.

---

## Diagnosis in the central office

| MQTT (`hb` in the last 30 s) | Backup (C4-B in the last 11 min) | Last information | Diagnosis |
|---|---|---|---|
| yes | — | `mode` normal | node OK |
| yes or no | yes or no | `mode` degraded/failsafe, or `FAULT` | node faulty (with the code) |
| no | yes | `mode` normal | network down, node healthy |
| no | no | `DEAD` received | Linux stuck, MCU alive |
| no | no | `TAMPER` (code 1 or 2) in the last 10 min | tampering (probable) |
| no | no | battery < 20% or dropping | battery flat (probable) |
| no | no | no warning | node destroyed or without power |

`TAMPER` code 3 (technician's NFC badge) is not an alarm: for 10 min the open door (code 2) does not count.

---

## Pinout (owner: Kuzey Bicher)

To be filled in. Pins needed by the communication:

| Pin | Component | Direction | Notes |
|---|---|---|---|
| D0/D1 (UART) | Grove Wio-E5 | MCU ↔ module | production only, 9600 baud |
| _?_ | door micro switch | MCU input | C5 `tamper` code 2 |
| _?_ | NFC reader | MCU | C5 `tamper` code 3 (technician badge) |
| _?_ (I2C) | LTC2941 | MCU | C5 `env.batt` |
| _?_ (I2C) | AHT20, light sensor | MCU | C5 `env` |

## Changelog

- v1 (10/10/2026): first version from §4 of `PROMPT_SMART_CROSSING.md` with the decisions of `comms/DECISIONS.md`.
- v1, same day (formats unchanged): local broker on the PC for the demo, generic cloud broker for production (no more
  AWS IoT Core); BLE receiver inside the central office.
- v1, same day (formats and function names unchanged): Linux side of the Bridge with the official library
  `arduino-router-bridge` (verified), instead of `arduino.app_utils` which exists only inside App Lab.
