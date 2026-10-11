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
          "nodo09": {"id": "nodo09", "name": "corso Francia", "lat": 45.05, "lon": 7.70}}


def test_state_nodes_alarms_traffic(store):
    s = state(store, CONFIG)
    n1, n2, n9 = s["nodes"]
    assert (n1["node"], n1["name"], n1["diagnosis"]["code"], n1["channel"]) == ("nodo01", "via Roma", "ok", "Wi-Fi/MQTT")
    assert (n1["lat"], n1["lon"], n1["site"]) == (45.0679, 7.6829, "urbano")
    assert (n9["diagnosis"]["code"], n9["lat"]) == ("unknown", 45.05), "camera configurata, nodo non ancora collegato"
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
    assert {"nodo01", "nodo02"} == {n["node"] for n in api.get_json()["nodes"]}, "nodi con dati + app/nodes.json"


def test_forecast_endpoint(store):
    """Flusso atteso (ai/forecast): risponde subito, senza rete, anche per una camera che non ha mai mandato dati."""
    from dashboard import load_forecaster
    assert load_forecaster() is not None, "da sorgente il modello si trova in ai/forecast"
    from forecast.context import Context
    from forecast.service import Forecaster
    offline = Forecaster(context=Context(None, {}, background=False))     # nessuna fonte esterna nei test
    client = create_app(store, CONFIG, forecaster=offline).test_client()
    f = client.get("/api/forecast/nodo01").get_json()
    assert f["available"] and f["mode"] == "fused" and f["history_windows"] == 2, "le due finestre di conteggi del nodo"
    assert set(f["estimate"]) == {"ped_in", "ped_out", "cyclist", "vehicles"}
    assert len(f["outlook"]) == 25 and f["outlook"][0]["now"], "adesso, poi le prossime 24 ore"
    g = client.get("/api/forecast/nodo09").get_json()
    assert g["mode"] == "model_only" and g["sources"]["located"], "camera sulla mappa ma senza dati: solo il modello"
    assert client.get("/api/forecast/mai-visto").get_json()["sources"]["located"] is False
    flow = client.get("/api/flow").get_json()["nodes"]
    assert set(flow) == {"nodo01", "nodo02", "nodo09"}, "tutte le camere: quelle con dati e quelle solo sulla mappa"
    assert all(n["available"] and len(n["outlook"]) == 25 for n in flow.values())

    class Broken:
        def forecast(self, *a):
            raise RuntimeError("boom")
    broken = create_app(store, CONFIG, forecaster=Broken()).test_client()
    assert broken.get("/api/forecast/nodo01").get_json()["available"] is False, "la dashboard non si ferma"
    assert broken.get("/api/flow").get_json()["nodes"]["nodo01"] == {"available": False, "error": "boom"}


def test_repo_nodes_json_is_valid():
    from dashboard import node_config
    cams = node_config()
    assert list(cams) == ["nodo01"], "solo il nodo vero: niente camere di esempio"
    assert all(-90 <= c["lat"] <= 90 and -180 <= c["lon"] <= 180 for c in cams.values())


def test_app_moves_the_default_camera_but_keeps_edited_files(tmp_path):
    """La camera di nodo01 è stata spostata: chi aveva già aperto l'app la ritrova nel posto nuovo, se non l'aveva toccata."""
    import json
    sys.path.insert(0, os.path.join(ROOT, "app", "desktop"))
    import centrale_app
    from dashboard import node_config
    nodes = tmp_path / "nodes.json"
    nodes.write_text(json.dumps({"_comment": "vecchio", "nodes": centrale_app.OLD_DEFAULT_CAMERAS}))
    centrale_app.prepare_home(str(tmp_path))
    cam = node_config(str(nodes))["nodo01"]
    assert cam == node_config()["nodo01"] and "Castelfidardo" in cam["name"] and (cam["lat"], cam["lon"]) == (45.0614, 7.6581)
    mine = {"nodes": [{"id": "nodo01", "name": "Via Roma, piazza San Carlo", "lat": 45.07, "lon": 7.68, "site": "urbano"}]}
    nodes.write_text(json.dumps(mine))
    centrale_app.prepare_home(str(tmp_path))
    assert json.loads(nodes.read_text()) == mine, "posizione cambiata a mano: non si tocca"


def test_old_example_cameras_are_ignored(tmp_path):
    """Chi ha già usato l'app ha nelle impostazioni il nodes.json vecchio, con le camere di esempio: non si mostrano."""
    from dashboard import node_config
    f = tmp_path / "nodes.json"
    f.write_text('{"nodes": [{"id": "nodo01", "lat": 45, "lon": 7, "mock": false},'
                 ' {"id": "nodo02", "lat": 45, "lon": 7, "mock": true}]}')
    assert list(node_config(str(f))) == ["nodo01"]
