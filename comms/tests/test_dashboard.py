"""Dashboard della centrale (app/dashboard.py): dati della pagina e risposte HTTP, senza rete né radio."""
import os
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (ROOT, os.path.join(ROOT, "comms", "node"), os.path.join(ROOT, "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

import ingest  # noqa: E402
import payload as P  # noqa: E402
from dashboard import create_app, state  # noqa: E402


@pytest.fixture
def store(tmp_path):
    s = ingest.Store(str(tmp_path / "central.db"))
    now = time.time()
    # nodo01: Wi-Fi ok, eventi, un allarme arrivato prima via BLE e poi via MQTT (backfill)
    s.set_hb("nodo01", {"v": 1, "node_id": "nodo01", "type": "hb", "online": True, "mode": "normal",
                        "state": "PRESENCE", "queue": 0, "batt": 87, "fps": 9.6})
    evs = [{"seq": i + 1, "ts": now - 100 + i, "type": "crossing", "cls": "pedestrian", "dir": "in",
            "attrs": {"slow": i == 0}} for i in range(3)]
    evs += [{"seq": 4, "ts": now - 50, "type": "yield", "yielded": True},
            {"seq": 5, "ts": now - 40, "type": "yield", "yielded": False},
            {"seq": 6, "ts": now - 30, "type": "near_miss", "a": 1, "b": 2},
            {"seq": 7, "ts": int(now - 20), "type": "incident", "kind": "person_down", "track_id": 9}]
    s.add_events("nodo01", evs)
    ingest.handle_backup(s, "nodo01", P.TYPE_INCIDENT, P.pack_alarm(int(now - 20), 1), "ble", -60)
    t0 = int(now // 60) * 60 - 120
    agg = P.summarize([{"type": "crossing", "cls": "pedestrian", "dir": "in"}] * 4, t0, t0 + 60, "nodo01")
    ingest.handle_backup(s, "nodo01", P.TYPE_AGG, P.pack_agg(agg, 0), "ble", -60)       # provvisorio...
    s.add_aggregate("nodo01", t0, "mqtt", False, dict(agg, counts={"pedestrian": {"in": 5, "out": 1}}))  # ...poi esatto
    agg2 = P.summarize([{"type": "crossing", "cls": "car", "dir": "in"}] * 7, t0 + 60, t0 + 120, "nodo01")
    ingest.handle_backup(s, "nodo01", P.TYPE_AGG, P.pack_agg(agg2, 30), "ble", -61)     # solo provvisorio
    # nodo02: solo BLE (Wi-Fi giù), manomissione
    ingest.handle_backup(s, "nodo02", P.TYPE_HB, P.pack_hb(now, "normal", "IDLE", 1234, 64, 80, 2), "ble", -67)
    ingest.handle_backup(s, "nodo02", P.TYPE_TAMPER, P.pack_alarm(int(now - 5), 2), "ble", -67)
    return s


CONFIG = {"nodo01": {"id": "nodo01", "name": "via Roma", "lat": 45.0679, "lon": 7.6829, "site": "urbano"},
          "nodo09": {"id": "nodo09", "name": "camera di esempio", "lat": 45.05, "lon": 7.70, "mock": True}}


def test_state_nodes_alarms_traffic(store):
    s = state(store, CONFIG)
    n1, n2, n9 = s["nodes"]
    assert (n1["node"], n1["name"], n1["diagnosis"]["code"], n1["channel"]) == ("nodo01", "via Roma", "ok", "Wi-Fi/MQTT")
    assert (n1["lat"], n1["lon"], n1["site"], n1["mock"]) == (45.0679, 7.6829, "urbano", False)
    assert (n9["diagnosis"]["code"], n9["mock"], n9["lat"]) == ("unknown", True, 45.05), "camera del mockup senza dati"
    assert n2["lat"] is None, "nodo con dati ma senza coordinate: in lista, non sulla mappa"
    assert (n1["state"], n1["queue"], n1["batt"], n1["fps"]) == ("PRESENCE", 0, 87, 9.6)
    assert (n2["diagnosis"]["text"], n2["channel"], n2["rssi"]) == ("rete giù, nodo sano", "BLE", -67)
    assert (n2["state"], n2["queue"], n2["batt"]) == ("IDLE", 1230, 64), "dati dall'HB arrivato via BLE"

    by_text = {a["text"]: a for a in s["alarms"]}
    assert by_text["persona a terra"]["via"] == ["BLE", "MQTT"], "stesso allarme da due canali: una riga sola"
    assert by_text["persona a terra"]["severity"] == "danger"
    assert by_text["sportello aperto"]["node"] == "nodo02"
    assert len(s["alarms"]) == 2

    t = s["traffic"]["nodo01"]
    assert [(w["ped_in"], w["vehicles"], w["provisional"]) for w in t["windows"]] == [(5, 0, False), (0, 7, True)], \
        "finestra esatta (MQTT) al posto della provvisoria; l'altra resta provvisoria"
    assert t["last_hour"]["ped_in"] == 5 and t["last_hour_provisional"]
    assert t["today"] == {"yield_rate": 0.5, "near_miss": 1, "vulnerable": 1}
    assert s["reliability"]["gaps"] == 0 and s["reliability"]["events"] == 7


def test_http_endpoints(store):
    client = create_app(store).test_client()
    page = client.get("/")
    assert page.status_code == 200 and b"Centrale MDGB" in page.data
    assert b"mappa schematica" in page.data, "senza Internet la mappa ripiega su quella schematica"
    api = client.get("/api/state")
    assert api.status_code == 200
    assert {"nodo01", "nodo02"} <= {n["node"] for n in api.get_json()["nodes"]}, "più le camere di app/nodes.json"


def test_repo_nodes_json_is_valid():
    from dashboard import node_config
    cams = node_config()
    assert cams and all(-90 <= c["lat"] <= 90 and -180 <= c["lon"] <= 180 for c in cams.values())
