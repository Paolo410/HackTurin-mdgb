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


def offline_forecaster(now=None):
    """Il modello vero, senza fonti esterne (niente rete nei test) e, se serve, con l'orologio fermo."""
    from dashboard import load_forecaster      # mette ai/ nel percorso dei moduli
    assert load_forecaster() is not None
    from forecast.context import Context
    from forecast.service import Forecaster
    return Forecaster(context=Context(None, {}, background=False), **({"clock": lambda: now} if now else {}))


def test_forecast_windows_exact_counts_first_and_oldest_first(store):
    from dashboard import forecast_windows
    ws = forecast_windows(store, "nodo01")
    assert [(w["ped_in"], w["ped_out"], w["vehicles"], w["provisional"]) for w in ws] == [(5, 1, 0, False), (0, 0, 7, True)], \
        "dove c'è, l'aggregato esatto (MQTT) al posto di quello provvisorio (Bluetooth)"
    assert ws[0]["t0"] < ws[1]["t0"] and all(w["t1"] - w["t0"] == 60 for w in ws)
    assert forecast_windows(store, "nodo01", n=1) == ws[-1:], "le più recenti"
    assert forecast_windows(store, "nodo02") == [] and forecast_windows(store, "mai-visto") == []


def test_flow_follows_the_counts_a_node_sends(tmp_path):
    """Dagli eventi della visione al riquadro: gli aggregati del nodo (payload.summarize, contratto C4) entrano nel
    database della centrale come li scrive l'ingest, e /api/flow restituisce una stima che li segue."""
    now = time.mktime((2026, 10, 12, 18, 0, 0, 0, 0, -1))                  # lunedì alle 18, ora locale
    s = ingest.Store(str(tmp_path / "central.db"))
    minute = ([{"type": "crossing", "cls": "pedestrian", "dir": "in"}] * 4 + [{"type": "crossing", "cls": "pedestrian", "dir": "out"}] * 2
              + [{"type": "crossing", "cls": "car", "dir": "in"}])
    for i in range(90):                                                    # un'ora e mezza di finestre da un minuto
        t0 = int(now) - 60 * (i + 1)
        s.add_aggregate("nodo01", t0, "mqtt", False, P.summarize(minute, t0, t0 + 60, "nodo01", {"t_c": 12.0, "rh": 70, "lux": 90}))
    client = create_app(s, CONFIG, forecaster=offline_forecaster(now)).test_client()
    flow = client.get("/api/flow").get_json()
    f = flow["nodes"]["nodo01"]
    assert f["mode"] == "fused" and f["history_windows"] == 90 and f["now"] == now
    est = f["estimate"]
    assert est["ped_in"]["mean"] == pytest.approx(60, rel=0.15), "4 pedoni al minuto sono 60 ogni quarto d'ora"
    assert est["ped_out"]["mean"] == pytest.approx(30, rel=0.15) and est["vehicles"]["mean"] == pytest.approx(15, rel=0.15)
    assert est["cyclist"]["mean"] < 1, "nessun ciclista contato"
    assert est["ped_in"]["lo"] < 60 < est["ped_in"]["hi"] and est["ped_in"]["node_weight"] > 0.6
    assert f["outlook"][0]["ped_in"] == pytest.approx(4 * est["ped_in"]["mean"], abs=0.2), "adesso, all'ora"
    assert f["outlook"][1]["t0"] == now + 3600 and f["outlook"][1]["ped_in"] > f["outlook"][10]["ped_in"], "le 19 contro le 4 di notte"
    assert f["anomaly"]["level"] == "normal" and f["anomaly"]["measured"] == 360, "un'ora a 6 pedoni al minuto"
    assert f["inputs"]["temp_c"] is None, "senza meteo: il termometro del nodo vale per le sue finestre, non per adesso"
    quiet = flow["nodes"]["nodo09"]
    assert quiet["mode"] == "model_only" and quiet["estimate"]["ped_in"]["mean"] < est["ped_in"]["mean"]
    assert client.get("/api/forecast/nodo01").get_json() == f, "la stessa stima dalle due strade"


def test_missing_model_is_looked_for_once_and_hides_the_panel(store, monkeypatch):
    import dashboard
    calls = []
    monkeypatch.setattr(dashboard, "load_forecaster", lambda: calls.append(1))        # ritorna None: modello assente
    client = create_app(store, CONFIG).test_client()
    for _ in range(3):
        flow = client.get("/api/flow")
        assert flow.status_code == 200 and all(n == {"available": False} for n in flow.get_json()["nodes"].values())
    assert client.get("/api/forecast/nodo01").get_json() == {"available": False}
    assert len(calls) == 1, "non si riprova a ogni aggiornamento della pagina"
    assert client.get("/api/state").status_code == 200, "il resto della dashboard non ne risente"


def test_load_forecaster_survives_a_broken_package(monkeypatch):
    import dashboard
    assert dashboard.load_forecaster() is not None
    monkeypatch.setitem(sys.modules, "forecast.service", None)                         # import impossibile
    assert dashboard.load_forecaster() is None


def test_selftest_of_the_app_wants_the_forecast_too(store, monkeypatch):
    """L'autotest della build (app/desktop/centrale_app.py --selftest) fallisce se nell'app manca il modello."""
    import dashboard
    sys.path.insert(0, os.path.join(ROOT, "app", "desktop"))
    import centrale_app
    info = lambda: {"mqtt": {"connected": True}}
    offline = offline_forecaster()
    for forecaster, expected in ((offline, True), (None, False)):
        monkeypatch.setattr(dashboard, "load_forecaster", lambda forecaster=forecaster: forecaster)
        srv = dashboard.serve(store, "127.0.0.1", 0, CONFIG, info)
        try:
            assert centrale_app.selftest("http://127.0.0.1:%d" % srv.server_port) is expected
        finally:
            srv.shutdown()
            srv.server_close()


def test_page_is_wired_to_what_exists(store):
    """Controlli statici sulla pagina: ogni elemento cercato per id c'è, ogni colore usato è definito nei due temi,
    ogni indirizzo chiamato è servito dalla centrale."""
    import re
    with open(os.path.join(ROOT, "app", "dashboard.html"), encoding="utf-8") as f:
        page = f.read()
    looked_up, present = set(re.findall(r'getElementById\("([\w-]+)"\)', page)), set(re.findall(r'id="([\w-]+)"', page))
    assert looked_up <= present, "id cercati ma assenti: %s" % (looked_up - present)
    light, dark = page.split("@media (prefers-color-scheme: dark)")[0], page.split("@media (prefers-color-scheme: dark)")[1].split("}")[0:3]
    used = set(re.findall(r"var\((--[\w-]+)\)", page))
    assert used <= set(re.findall(r"(--[\w-]+)\s*:", light)), "variabili CSS usate ma non definite"
    assert {"--halo", "--halo-soft", "--bar"} <= set(re.findall(r"(--[\w-]+)\s*:", "".join(dark))), "anche nel tema scuro"
    rules = [str(r) for r in create_app(store, CONFIG, forecaster=offline_forecaster()).url_map.iter_rules()]
    for path in set(re.findall(r'fetch\([`"](/api/[\w/]+)', page)):
        assert any(path == r or (("<" in r) and path.startswith(r.split("<")[0])) for r in rules), "la pagina chiama %s" % path
    assert "/api/flow" in page and 'id="flow-range"' in page and "mk-halo" in page and "halo-legend" in page
    for leftover in ("forecastView", "refreshForecast", "fcNode"):
        assert leftover not in page, "resti della prima versione del riquadro"


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
