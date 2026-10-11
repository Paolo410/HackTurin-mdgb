"""Dati che escono dalla centrale: API per i clienti con chiave (app/customers.py) e stime e metriche su MQTT
(app/publisher.py). Senza rete e senza broker: il modello è quello vero, con l'orologio fermo e nessuna fonte esterna."""
import json
import os
import sqlite3
import sys
import time

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for p in (ROOT, os.path.join(ROOT, "comms", "node"), os.path.join(ROOT, "app")):
    if p not in sys.path:
        sys.path.insert(0, p)

import customers  # noqa: E402
import ingest  # noqa: E402
import payload as P  # noqa: E402
import publisher  # noqa: E402
from dashboard import Flow, create_app, load_forecaster  # noqa: E402

NOW = time.mktime((2026, 10, 12, 18, 0, 0, 0, 0, -1))                 # lunedì alle 18, ora locale
CONFIG = {"nodo01": {"id": "nodo01", "name": "Corso Castelfidardo", "lat": 45.0614, "lon": 7.6581, "site": "urbano"},
          "nodo02": {"id": "nodo02", "name": "Corso Duca degli Abruzzi", "lat": 45.0628, "lon": 7.6624},     # a 370 m
          "nodo09": {"id": "nodo09", "name": "Piazza San Carlo", "lat": 45.0679, "lon": 7.6829},             # a 2 km
          "nodo10": {"id": "nodo10", "name": "senza posizione"}}
NEAR = {"lat": 45.0614, "lon": 7.6581, "radius_m": 500}
MINUTE = ([{"type": "crossing", "cls": "pedestrian", "dir": "in"}] * 4 + [{"type": "crossing", "cls": "pedestrian", "dir": "out"}] * 2
          + [{"type": "crossing", "cls": "car", "dir": "in"}])


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Centrale con nodo01 che conta da un'ora e mezza, le altre camere mute; l'orologio è fermo a lunedì alle 18."""
    monkeypatch.setattr(time, "time", lambda: NOW)
    assert load_forecaster() is not None
    from forecast.context import Context
    from forecast.service import Forecaster
    s = ingest.Store(str(tmp_path / "central.db"))
    for i in range(90):
        t0 = int(NOW) - 60 * (i + 1)
        s.add_aggregate("nodo01", t0, "mqtt", False, P.summarize(MINUTE, t0, t0 + 60, "nodo01", {"t_c": 12.0}))
    events = [{"seq": i + 1, "ts": NOW - 60 * i - 5, "type": "crossing", "cls": "pedestrian", "dir": "in",
               "attrs": {"slow": i % 10 == 0}} for i in range(50)]
    events += [{"seq": 51 + i, "ts": NOW - 300 * i - 7, "type": "yield", "yielded": i % 4 != 0} for i in range(8)]
    events += [{"seq": 60, "ts": NOW - 900, "type": "near_miss", "a": 1, "b": 2},
               {"seq": 61, "ts": NOW - 1200, "type": "incident", "kind": "hard_brake"},
               {"seq": 62, "ts": NOW - 2 * 86400, "type": "near_miss", "a": 3, "b": 4}]            # due giorni fa: non conta
    s.add_events("nodo01", events)
    flow = Flow(s, CONFIG, Forecaster(context=Context(None, {}, background=False), clock=lambda: NOW))
    keys = customers.KeyStore(s.db, s.lock)
    client = create_app(s, CONFIG, flow=flow).test_client()

    class World:
        pass
    w = World()
    w.store, w.flow, w.keys, w.client = s, flow, keys, client
    w.get = lambda path, key=None, **kw: client.get(path, headers={"X-API-Key": key} if key else {}, **kw)
    return w


# ---------------------------------------------------------------- chiavi
def test_key_is_shown_once_and_only_its_fingerprint_is_stored(world):
    made = world.keys.create("  Bar   Sport ", NEAR, days=30, now=NOW)
    assert made["key"].startswith("mdgb_%s_" % made["id"]) and len(made["key"]) > 40 and made["name"] == "Bar Sport"
    assert made["expires"] == NOW + 30 * 86400 and made["scopes"] == ["realtime", "forecast"]
    stored = world.store.db.execute("SELECT * FROM api_keys").fetchall()
    assert len(stored) == 1 and made["key"] not in json.dumps(stored), "nel database non c'è la chiave"
    assert all("key" not in k and "key_hash" not in k for k in world.keys.list()), "né nell'elenco"
    other = world.keys.create("Altro", NEAR)
    assert other["key"] != made["key"] and other["id"] != made["id"] and other["expires"] is None


def test_key_check_unknown_tampered_expired_revoked(world):
    made = world.keys.create("Bar Sport", NEAR, days=1, now=NOW)
    ok, why = world.keys.check(made["key"], now=NOW + 10)
    assert why is None and (ok["id"], ok["name"], ok["zone"]) == (made["id"], "Bar Sport", NEAR)
    for bad, reason in (("", "mancante"), (None, "mancante"), ("ciao", "malformata"), ("mdgb_ffffffff_xyz", "sconosciuta"),
                        (made["key"][:-1] + ("A" if made["key"][-1] != "A" else "B"), "sconosciuta"),
                        (made["key"].upper(), "malformata")):
        key, why = world.keys.check(bad, now=NOW)
        assert key is None and reason in why, bad
    assert "scaduta" in world.keys.check(made["key"], now=NOW + 86400)[1]
    assert world.keys.revoke(made["id"]) is True and world.keys.revoke(made["id"]) is False
    assert "revocata" in world.keys.check(made["key"], now=NOW)[1]
    assert world.keys.revoke("nessuna") is False


def test_key_needs_a_name_a_valid_zone_and_something_to_read(world):
    create = world.keys.create
    for name in ("", "   ", None, "x" * 81):
        with pytest.raises(ValueError, match="nome"):
            create(name, NEAR)
    for zone in (None, {}, {"lat": 45.0}, {"lat": "nord", "lon": 7.0, "radius_m": 100}, {"lat": 95.0, "lon": 7.0, "radius_m": 100},
                 {"lat": 45.0, "lon": 7.0, "radius_m": 10}, {"lat": 45.0, "lon": 7.0, "radius_m": 50000}, {"nodes": "nodo01"},
                 {"nodes": [1, 2]}):
        with pytest.raises(ValueError):
            create("Bar", zone)
    with pytest.raises(ValueError, match="tipo di dati"):
        create("Bar", NEAR, scopes=["tutto"])
    with pytest.raises(ValueError, match="giorni"):
        create("Bar", NEAR, days=0)
    assert create("Comune", {"nodes": ["nodo02", "nodo01", "nodo01"]})["zone"] == {"nodes": ["nodo01", "nodo02"]}
    assert create("Solo previsioni", NEAR, scopes=["forecast"])["scopes"] == ["forecast"]
    assert world.keys.list()[0]["name"] in ("Comune", "Solo previsioni") and len(world.keys.list()) == 2, "le chiavi non create non lasciano traccia"


def test_zone_is_a_circle_on_the_map_or_a_list_of_nodes():
    assert customers.distance_m(45.0614, 7.6581, 45.0614, 7.6581) == 0
    assert customers.distance_m(45.0, 7.0, 46.0, 7.0) == pytest.approx(111195, rel=0.002), "un grado di latitudine"
    assert customers.distance_m(45.0614, 7.6581, 45.0628, 7.6624) == pytest.approx(372, abs=8)
    near = customers.cameras_in(NEAR, CONFIG)
    assert [c["id"] for c in near] == ["nodo01", "nodo02"], "dalla più vicina; quella a 2 km e quella senza posizione no"
    assert near[0]["distance_m"] == 0 and near[1]["distance_m"] == pytest.approx(372, abs=8) and near[1]["name"] == "Corso Duca degli Abruzzi"
    assert [c["id"] for c in customers.cameras_in(dict(NEAR, radius_m=300), CONFIG)] == ["nodo01"]
    assert customers.cameras_in({"lat": 44.0, "lon": 8.0, "radius_m": 20000}, CONFIG) == []
    by_name = customers.cameras_in({"nodes": ["nodo10", "nodo09", "mai-visto"]}, CONFIG)
    assert [c["id"] for c in by_name] == ["nodo09", "nodo10"] and by_name[1]["lat"] is None


# ---------------------------------------------------------------- API
def test_api_asks_for_a_key_in_the_header(world):
    key = world.keys.create("Bar Sport", NEAR)["key"]
    assert world.get("/api/v1/").status_code == 200 and "/api/v1/forecast" in world.get("/api/v1/").get_json()["endpoints"]
    for path in ("/api/v1/zone", "/api/v1/realtime", "/api/v1/forecast", "/api/v1/history", "/api/v1/metrics"):
        assert world.get(path).status_code == 401 and "error" in world.get(path).get_json()
        assert world.get(path, "mdgb_00000000_sbagliata").status_code == 401
        assert world.get(path + "?key=" + key).status_code == 401, "la chiave nell'indirizzo finirebbe nei log: non vale"
        assert world.get(path, key).status_code == 200
        assert world.client.get(path, headers={"Authorization": "Bearer " + key}).status_code == 200
    world.keys.revoke(key.split("_")[1])
    assert world.get("/api/v1/zone", key).status_code == 401 and "revocata" in world.get("/api/v1/zone", key).get_json()["error"]


def test_api_zone_and_realtime(world):
    key = world.keys.create("Bar Sport", NEAR)["key"]
    zone = world.get("/api/v1/zone", key).get_json()
    assert zone["available"] is True and zone["customer"] == "Bar Sport" and zone["zone"] == NEAR
    assert [c["id"] for c in zone["cameras"]] == ["nodo01", "nodo02"] and zone["generated_at_iso"].endswith("Z")

    rt = world.get("/api/v1/realtime", key).get_json()
    counting, silent = rt["cameras"]
    assert counting["last_window"] == {"ped_in": 4, "ped_out": 2, "cyclist": 0, "vehicles": 1, "t0": NOW - 60, "t1": NOW,
                                       "t0_iso": customers.iso(NOW - 60), "provisional": False}
    assert counting["last_hour"] == {"ped_in": 240, "ped_out": 120, "cyclist": 0, "vehicles": 60} and counting["last_data_s"] == 0
    est = counting["estimate_per_hour"]
    assert est["ped_in"]["mean"] == pytest.approx(240, rel=0.15) and est["ped_in"]["low"] < est["ped_in"]["mean"] < est["ped_in"]["high"]
    assert counting["estimate_from"] == "model_and_counts"
    assert (silent["last_window"], silent["last_hour"], silent["last_data_s"]) == (None, None, None), "camera che non conta"
    assert silent["estimate_from"] == "model_only" and silent["estimate_per_hour"]["ped_in"]["mean"] > 0
    assert rt["zone_estimate_per_hour"]["ped_in"] == pytest.approx(est["ped_in"]["mean"] + silent["estimate_per_hour"]["ped_in"]["mean"], abs=0.2)
    assert "simulato" in rt["notice_model"]


def test_api_forecast_hours_and_zone_total(world):
    key = world.keys.create("Bar Sport", NEAR)["key"]
    fc = world.get("/api/v1/forecast", key).get_json()
    first, second = fc["cameras"]
    assert len(first["hours"]) == 24 and first["hours"][0]["t0"] == NOW + 3600 and first["hours"][0]["t0_iso"] == customers.iso(NOW + 3600)
    assert set(first["hours"][0]) == {"ped_in", "ped_out", "cyclist", "vehicles", "t0", "t1", "t0_iso"}
    assert first["hours"][0]["ped_in"] > first["hours"][8]["ped_in"], "le 19 contro le 3 di notte"
    assert len(fc["zone_hours"]) == 24
    assert fc["zone_hours"][3]["ped_in"] == pytest.approx(first["hours"][3]["ped_in"] + second["hours"][3]["ped_in"], abs=0.2)
    assert len(world.get("/api/v1/forecast?hours=3", key).get_json()["cameras"][0]["hours"]) == 3
    for odd in ("0", "-5", "999", "tante"):
        n = len(world.get("/api/v1/forecast?hours=" + odd, key).get_json()["cameras"][0]["hours"])
        assert 1 <= n <= 24, "richieste strane non rompono nulla"


def test_api_history_and_csv_downloads(world):
    key = world.keys.create("Bar Sport", NEAR)["key"]
    hist = world.get("/api/v1/history?hours=1", key).get_json()
    assert len(hist["cameras"][0]["windows"]) == 60 and hist["cameras"][1]["windows"] == []
    assert hist["cameras"][0]["windows"][-1]["ped_in"] == 4 and hist["cameras"][0]["windows"][0]["t0"] == NOW - 3600
    assert len(world.get("/api/v1/history", key).get_json()["cameras"][0]["windows"]) == 90, "tutto quello che c'è nelle 24 ore"

    table = world.get("/api/v1/history?hours=1&format=csv", key)
    assert table.mimetype == "text/csv" and "attachment" in table.headers["Content-Disposition"]
    lines = table.get_data(as_text=True).strip().split("\n")
    assert lines[0] == "camera,name,t0,t0_iso,t1,ped_in,ped_out,cyclist,vehicles,provisional" and len(lines) == 61
    assert lines[-1] == "nodo01,Corso Castelfidardo,%d,%s,%d,4,2,0,1,0" % (NOW - 60, customers.iso(NOW - 60), NOW)
    forecast = world.get("/api/v1/forecast?hours=2&format=csv", key).get_data(as_text=True).strip().split("\n")
    assert forecast[0] == "camera,name,t0,t0_iso,t1,ped_in,ped_out,cyclist,vehicles" and len(forecast) == 1 + 2 * 2


def test_api_metrics(world):
    key = world.keys.create("Bar Sport", NEAR)["key"]
    m = world.get("/api/v1/metrics", key).get_json()["cameras"][0]
    traffic, safety = m["metrics"]["traffic"], m["metrics"]["safety"]
    assert traffic["last_hour"]["ped_in"] == 240 and traffic["last_24h"]["ped_in"] == 360 and traffic["share_in"] == 0.67
    assert len(traffic["hourly"]) == 24 and traffic["hourly"][-1]["t0"] == NOW, "l'ora in corso è l'ultima"
    assert traffic["hourly"][-2]["ped_in"] == 240 and traffic["hourly"][-2]["coverage"] == 1.0
    assert traffic["peak_hour"] == {"t0": NOW - 3600, "t1": NOW, "pedestrians": 360}
    assert traffic["coverage_24h"] == pytest.approx(1.5 / 24, abs=0.001) and traffic["pedestrians_per_hour"] == 360
    assert safety == {"pedestrian_crossings": 50, "vulnerable": 5, "vulnerable_share": 0.1, "vehicles_met": 8, "yield_rate": 0.75,
                      "near_miss": 1, "near_miss_per_1000_crossings": 20.0, "incidents": 1, "incidents_by_kind": {"hard_brake": 1}}
    check = m["estimate_check"]
    assert check["windows"] == 48 and check["window_s"] == 60 and check["mae"] < check["mae_model"], "la stima batte il solo modello"


def test_api_without_cameras_in_the_zone_says_so(world):
    key = world.keys.create("Negozio a Genova", {"lat": 44.41, "lon": 8.93, "radius_m": 1000})["key"]
    for path in ("/api/v1/zone", "/api/v1/realtime", "/api/v1/forecast", "/api/v1/history", "/api/v1/metrics"):
        r = world.get(path, key)
        body = r.get_json()
        assert r.status_code == 200 and body["available"] is False and body["cameras"] == [] and "Nessuna camera" in body["notice"]
    assert world.get("/api/v1/realtime", key).get_json()["zone_estimate_per_hour"] is None
    assert world.get("/api/v1/forecast?format=csv", key).get_data(as_text=True).strip().count("\n") == 0, "solo l'intestazione"


def test_api_scopes_usage_and_rate_limit(world):
    only_forecast = world.keys.create("Solo previsioni", NEAR, scopes=["forecast"])
    key = only_forecast["key"]
    assert world.get("/api/v1/forecast", key).status_code == 200 and world.get("/api/v1/zone", key).status_code == 200
    for path in ("/api/v1/realtime", "/api/v1/history", "/api/v1/metrics"):
        r = world.get(path, key)
        assert r.status_code == 403 and "realtime" in r.get_json()["error"]
    used = {k["id"]: k for k in world.keys.list()}[only_forecast["id"]]
    assert (used["requests_total"], used["requests_today"], used["last_used"]) == (2, 2, NOW), "si contano solo le richieste servite"

    limited = create_app(world.store, CONFIG, flow=world.flow).test_client()
    bp_limit = customers.RateLimit(per_minute=3, clock=lambda: NOW)
    assert [bp_limit.allow("a") for _ in range(5)] == [True, True, True, False, False] and bp_limit.allow("b") is True
    later = customers.RateLimit(per_minute=1, clock=lambda: clock[0])
    clock = [NOW]
    assert later.allow("a") and not later.allow("a")
    clock[0] += 60
    assert later.allow("a"), "il minuto dopo si riparte"
    assert limited.get("/api/v1/zone", headers={"X-API-Key": key}).status_code == 200


def test_api_rate_limit_answers_429(world):
    from flask import Flask
    key = world.keys.create("Bar Sport", NEAR)["key"]
    app = Flask(__name__)
    app.register_blueprint(customers.blueprint(world.keys, world.flow, customers.RateLimit(per_minute=2, clock=lambda: NOW)))
    client = app.test_client()
    codes = [client.get("/api/v1/zone", headers={"X-API-Key": key}).status_code for _ in range(4)]
    assert codes == [200, 200, 429, 429]
    refused = client.get("/api/v1/zone", headers={"X-API-Key": key})
    assert refused.headers["Retry-After"] == "60" and "troppe richieste" in refused.get_json()["error"]
    assert {k["name"]: k["requests_total"] for k in world.keys.list()}["Bar Sport"] == 2


def test_keys_are_managed_only_from_the_control_room_pc(world):
    outside = {"REMOTE_ADDR": "192.168.1.50"}
    made = world.client.post("/api/keys", json={"name": "Bar Sport", "zone": NEAR, "days": 7})
    assert made.status_code == 200 and made.get_json()["key"].startswith("mdgb_") and made.get_json()["cameras"] == ["nodo01", "nodo02"]
    key_id = made.get_json()["id"]
    listed = world.client.get("/api/keys").get_json()
    assert [k["id"] for k in listed["keys"]] == [key_id] and listed["keys"][0]["state"] == "active" and "key" not in listed["keys"][0]
    assert world.client.post("/api/keys", json={"name": "", "zone": NEAR}).status_code == 400
    assert world.client.post("/api/keys", data="non json", content_type="text/plain").status_code == 400
    for method, path in (("get", "/api/keys"), ("post", "/api/keys"), ("delete", "/api/keys/" + key_id)):
        r = getattr(world.client, method)(path, environ_base=outside, json={"name": "Intruso", "zone": NEAR})
        assert r.status_code == 403, "dalla rete locale la dashboard si può guardare, le chiavi no"
    assert len(world.keys.list()) == 1
    assert world.client.get("/api/v1/zone", headers={"X-API-Key": made.get_json()["key"]}, environ_base=outside).status_code == 200, \
        "i dati invece si leggono da fuori, con la chiave"
    assert world.client.delete("/api/keys/" + key_id).get_json() == {"revoked": True}
    assert world.client.delete("/api/keys/" + key_id).status_code == 404
    assert world.client.get("/api/keys").get_json()["keys"][0]["state"] == "revoked"


def test_command_line_creates_lists_and_revokes(tmp_path, capsys):
    db = str(tmp_path / "central.db")
    customers.main(["--db", db, "create", "--name", "Bar Sport", "--lat", "45.0614", "--lon", "7.6581", "--radius", "400", "--days", "30"])
    out = capsys.readouterr().out
    key = [w for w in out.split() if w.startswith("mdgb_")][0]
    keys = customers.KeyStore(sqlite3.connect(db, isolation_level=None))
    assert keys.check(key)[0]["zone"] == {"lat": 45.0614, "lon": 7.6581, "radius_m": 400}
    customers.main(["--db", db, "create", "--name", "Comune", "--nodes", "nodo01,nodo02", "--scopes", "forecast"])
    capsys.readouterr()
    customers.main(["--db", db, "list"])
    listed = capsys.readouterr().out
    assert "Bar Sport" in listed and "Comune" in listed and "active" in listed and key not in listed
    with pytest.raises(SystemExit, match="non creata"):
        customers.main(["--db", db, "create", "--name", "Senza zona"])
    customers.main(["--db", db, "revoke", key.split("_")[1]])
    assert "revocata" in capsys.readouterr().out and keys.check(key)[0] is None


# ---------------------------------------------------------------- MQTT
class FakeMqtt:
    def __init__(self, connected=True):
        self.connected, self.sent = connected, []

    def is_connected(self):
        return self.connected

    def publish(self, topic, payload, qos=0, retain=False):
        self.sent.append((topic, json.loads(payload), qos, retain))


def test_publisher_sends_forecast_and_analytics_of_every_camera(world):
    mqtt = FakeMqtt()
    assert publisher.publish(mqtt, world.flow, "mdgb") == 2 * len(CONFIG)
    by_topic = {t: (m, qos, retain) for t, m, qos, retain in mqtt.sent}
    assert set(by_topic) == {"mdgb/%s/%s" % (n, k) for n in CONFIG for k in ("forecast", "analytics")}
    assert all(qos == 1 and retain is True for m, qos, retain in by_topic.values()), "chi si collega riceve l'ultimo valore"
    assert not {t.split("/")[-1] for t in by_topic} & {"events", "agg", "hb", "backup"}, "mai sugli argomenti che la centrale ascolta"

    f = by_topic["mdgb/nodo01/forecast"][0]
    assert (f["v"], f["node_id"], f["type"], f["ts"], f["from"]) == (1, "nodo01", "forecast", NOW, "model_and_counts")
    assert f["now"]["ped_in"]["mean"] == pytest.approx(240, rel=0.15) and f["now"]["ped_in"]["low"] < f["now"]["ped_in"]["high"]
    assert len(f["hours"]) == 24 and f["hours"][0] == dict(f["hours"][0], t0=NOW + 3600) and f["model"] == {"trained_on": "simulated"}
    assert by_topic["mdgb/nodo09/forecast"][0]["from"] == "model_only"
    a = by_topic["mdgb/nodo01/analytics"][0]
    assert (a["type"], a["traffic"]["last_hour"]["ped_in"], a["safety"]["yield_rate"]) == ("analytics", 240, 0.75)
    assert a["estimate_check"]["windows"] == 48 and by_topic["mdgb/nodo09/analytics"][0]["estimate_check"] is None
    assert all(len(json.dumps(m)) < 8000 for m, _, _ in by_topic.values()), "messaggi piccoli"


def test_publisher_keeps_its_period_and_waits_for_the_broker(world):
    clock, mqtt = [NOW], FakeMqtt(connected=False)
    pub = publisher.Publisher(mqtt, world.flow, "mdgb", period_s=30, clock=lambda: clock[0])
    assert pub.tick() == 0 and mqtt.sent == [], "broker non collegato: niente"
    mqtt.connected = True
    assert pub.tick() == 8 and pub.tick() == 0, "appena collegato pubblica, poi aspetta"
    clock[0] += 29
    assert pub.tick() == 0
    clock[0] += 1
    assert pub.tick() == 8 and pub.sent == 16
    off = publisher.Publisher(FakeMqtt(), world.flow, period_s=0)
    assert off.tick() == 0, "ANALYTICS_PERIOD_S=0 spegne la pubblicazione"


def test_publisher_survives_a_missing_model_and_a_failing_broker(world, monkeypatch):
    import dashboard
    monkeypatch.setattr(dashboard, "load_forecaster", lambda: None)
    assert publisher.publish(FakeMqtt(), Flow(world.store, CONFIG), "mdgb") == 0, "senza modello non c'è niente da pubblicare"

    class Broken(FakeMqtt):
        def publish(self, *a, **k):
            raise OSError("broker caduto")
    assert publisher.publish(Broken(), world.flow, "mdgb") == 0, "si riprova al giro dopo, la centrale non si ferma"
