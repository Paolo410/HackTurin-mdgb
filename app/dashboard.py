"""Dashboard della centrale: pagina web servita da central.py (Flask), dati letti dal database della centrale.

    GET /            la pagina (app/dashboard.html, nessuna risorsa esterna: funziona senza Internet)
    GET /api/state   tutto quello che la pagina mostra, in JSON (aggiornato dalla pagina ogni 2 s)
    GET /api/info    stato della centrale stessa (MQTT, Bluetooth, cartella delle impostazioni)
    POST /api/open/folder|config   apre la cartella delle impostazioni o il file di configurazione (app per il PC)

Cosa mostra: mappa delle camere (posizioni in app/nodes.json; con Internet OpenStreetMap, senza una mappa schematica),
stato di ogni nodo (diagnosi, canale attivo, coda, batteria, semaforo), allarmi arrivati via MQTT o via
backup, traffico per finestra (esatto o provvisorio), sicurezza (precedenza, near-miss, vulnerabili) e affidabilità
della rete (eventi persi, doppioni scartati). Nessuna immagine: la centrale riceve solo dati anonimi.
"""
import json
import os
import subprocess
import sys
import time

from diagnosis import LABELS

ALARM_EVENT_TYPES = ("incident", "tamper", "lamp_fault", "failsafe")
TAMPER = {1: "shock_or_tilt", 2: "door_open", 3: "authorized_badge"}
VEHICLES = ("car", "motorcyclist", "bus", "truck")
ANIMALS = ("animal", "bird")


def node_config(path=None):
    """Camere della mappa: app/nodes.json (o NODES_FILE) -> {id: {name, lat, lon, site, mock}}."""
    path = path or os.environ.get("NODES_FILE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "nodes.json")
    try:
        with open(path, encoding="utf-8") as f:
            return {n["id"]: n for n in json.load(f).get("nodes", [])}
    except FileNotFoundError:
        return {}


def _alarm_from_event(ev):
    """Evento di allarme arrivato via MQTT -> (alarm, detail)."""
    t = ev.get("type")
    if t == "incident":
        return "incident", ev.get("kind", "unknown")
    if t == "tamper":
        return "tamper", TAMPER.get(ev.get("code"), "unknown")
    if t == "lamp_fault":
        return "fault", "lamp_fault"
    return "fault", "firmware_failsafe"


def _severity(alarm, detail):
    if detail == "authorized_badge":
        return "info"
    return "danger" if alarm in ("incident", "tamper", "dead") else "warning"


def _window(data, source):
    """Aggregato C4 (MQTT, esatto) o AGG C4-B (backup, provvisorio) -> stessa forma."""
    if source == "mqtt":
        c = data.get("counts", {})
        tot = lambda classes: sum(c.get(k, {}).get("in", 0) + c.get(k, {}).get("out", 0) for k in classes)
        ped = c.get("pedestrian", {})
        w = {"ped_in": ped.get("in", 0), "ped_out": ped.get("out", 0), "cyclist": tot(("cyclist",)),
             "vehicles": tot(VEHICLES), "animals": tot(ANIMALS)}
    else:
        w = {"ped_in": data["pedestrian"]["in"], "ped_out": data["pedestrian"]["out"], "cyclist": data["cyclist"],
             "vehicles": data["vehicles"], "animals": data["animals"]}
    w.update(t0=data["t0"], t1=data["t1"], provisional=source != "mqtt", env=data.get("env") or {})
    return w


def state(store, config=None, now=None, windows=12, **diag_windows):
    """config: camere di nodes.json (node_config()). diag_windows: soglie della diagnosi, accorciate nei test."""
    now = time.time() if now is None else now
    config = node_config() if config is None else config
    names = {k: v.get("name", "") for k, v in config.items()}
    midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
    report = {r["node"]: r for r in store.report()}
    nodes, alarms, traffic = [], [], {}
    for node in sorted(set(store.nodes()) | set(config)):
        diag = store.diagnose(node, now, **diag_windows)
        with store.lock:
            hb_row = store.db.execute("SELECT data, rx_at FROM hb WHERE node=?", (node,)).fetchone()
            bhb = store.db.execute("SELECT data, rx_at, rssi, via FROM backup WHERE node=? AND type=2 "
                                   "ORDER BY rx_at DESC LIMIT 1", (node,)).fetchone()
            last_ble = store.db.execute("SELECT rx_at, rssi FROM backup WHERE node=? ORDER BY rx_at DESC LIMIT 1",
                                        (node,)).fetchone()
            aggs = store.db.execute("SELECT window_start, source, data FROM aggregates WHERE node=? "
                                    "ORDER BY window_start DESC LIMIT ?", (node, 4 * windows)).fetchall()
            ev_alarms = store.db.execute(
                f"SELECT body, rx_at FROM events WHERE node=? AND type IN ({','.join('?' * len(ALARM_EVENT_TYPES))}) "
                "ORDER BY seq DESC LIMIT 50", (node, *ALARM_EVENT_TYPES)).fetchall()
            b_alarms = store.db.execute("SELECT data, rx_at, via FROM backup WHERE node=? AND type IN (9,10,11,12) "
                                        "ORDER BY rx_at DESC LIMIT 50", (node,)).fetchall()
            today = store.db.execute("SELECT type, body FROM events WHERE node=? AND ts>=? "
                                     "AND type IN ('yield','near_miss','crossing')", (node, midnight)).fetchall()

        hb, hb_rx = (json.loads(hb_row[0]), hb_row[1]) if hb_row else ({}, None)
        b = (json.loads(bhb[0]), bhb[1]) if bhb else ({}, None)
        # informazione più recente sul nodo: hb MQTT, oppure HB del backup se è più nuovo o se MQTT ha dato il Last Will
        newest = b if b[1] is not None and ((b[1] > (hb_rx or 0)) or hb.get("online") is False) else (hb, hb_rx)
        src = newest[0]
        cfg = config.get(node, {})
        nodes.append({
            "node": node, "name": names.get(node, ""), "diagnosis": diag,
            "lat": cfg.get("lat"), "lon": cfg.get("lon"), "site": cfg.get("site"), "mock": bool(cfg.get("mock")),
            "channel": {"mqtt": "Wi-Fi/MQTT", "ble": "BLE", "lorawan": "LoRaWAN"}.get(diag["via"]) if diag["via"] else None,
            "last_contact_s": None if diag["last_contact"] is None else round(now - diag["last_contact"], 1),
            "mqtt_silent_s": None if hb_rx is None else round(now - hb_rx, 1),
            "state": src.get("state"), "mode": src.get("mode"), "fps": hb.get("fps"),
            "queue": src.get("queue", src.get("backlog")), "batt": src.get("batt"),
            "rssi": last_ble[1] if last_ble else None,
            "ble_last_s": round(now - last_ble[0], 1) if last_ble else None,
        })

        # allarmi: lo stesso allarme può arrivare via BLE (subito) e poi via MQTT (backfill): uno solo, con i canali
        merged = {}
        for body, rx_at in ev_alarms:
            ev = json.loads(body)
            alarm, detail = _alarm_from_event(ev)
            key = (alarm, detail, int(ev.get("ts") or 0))
            merged.setdefault(key, {"rx_at": rx_at, "via": set()})["via"].add("MQTT")
        for data, rx_at, via in b_alarms:
            d = json.loads(data)
            key = (d["alarm"], d.get("detail", "dead"), int(d.get("ts") or rx_at))
            m = merged.setdefault(key, {"rx_at": rx_at, "via": set()})
            m["via"].add(via.upper())
            m["rx_at"] = min(m["rx_at"], rx_at)
        for (alarm, detail, ts), m in merged.items():
            alarms.append({"node": node, "name": names.get(node, ""), "alarm": alarm, "detail": detail,
                           "text": LABELS.get(detail, detail), "severity": _severity(alarm, detail),
                           "ts": ts or m["rx_at"], "via": sorted(m["via"])})

        # traffico: per ogni finestra l'aggregato esatto (MQTT) se c'è, altrimenti quello provvisorio del backup
        by_t0 = {}
        for t0, source, data in aggs:
            if t0 not in by_t0 or source == "mqtt":
                by_t0[t0] = _window(json.loads(data), source)
        ws = [by_t0[t] for t in sorted(by_t0)][-windows:]
        hour = [w for w in ws if w["t1"] > now - 3600]
        env = next((w["env"] for w in reversed(ws) if any(v is not None for v in w["env"].values())), {})
        yields = [json.loads(b_).get("yielded") for t, b_ in today if t == "yield"]
        traffic[node] = {
            "windows": ws,
            "last_hour": {k: sum(w[k] for w in hour) for k in ("ped_in", "ped_out", "cyclist", "vehicles", "animals")},
            "last_hour_provisional": any(w["provisional"] for w in hour),
            "env": env,
            "today": {"yield_rate": round(sum(map(bool, yields)) / len(yields), 2) if yields else None,
                      "near_miss": sum(1 for t, _ in today if t == "near_miss"),
                      "vulnerable": sum(1 for t, b_ in today if t == "crossing" and _vulnerable(json.loads(b_)))},
        }

    alarms.sort(key=lambda a: a["ts"], reverse=True)
    with store.lock:
        n_backup = store.db.execute("SELECT COUNT(*) FROM backup").fetchone()[0]
    rel = {"events": sum(r["events"] for r in report.values()), "gaps": sum(r["gaps"] for r in report.values()),
           "duplicates_dropped": store.dups, "backup_messages": n_backup}
    return {"now": now, "nodes": nodes, "alarms": alarms[:20], "traffic": traffic, "reliability": rel}


def _vulnerable(ev):
    a = ev.get("attrs") or {}
    return ev.get("cls") == "pedestrian" and bool(a.get("child") or a.get("slow") or a.get("aid") not in (None, "normal"))


def open_path(path, edit=False):
    """Apre una cartella o un file con l'app predefinita del sistema (Finder / TextEdit su macOS)."""
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-e", path] if edit else ["open", path])
    elif sys.platform.startswith("win"):
        os.startfile(path)                                       # noqa: S606 (solo percorsi della centrale)
    else:
        subprocess.Popen(["xdg-open", path])


def create_app(store, config=None, info=None):
    from flask import Flask, Response, abort, jsonify

    app = Flask(__name__)
    page = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.html")

    @app.get("/")
    def index():
        with open(page, encoding="utf-8") as f:
            return Response(f.read(), mimetype="text/html")

    @app.get("/api/state")
    def api_state():
        return jsonify(state(store, config))

    @app.get("/api/info")
    def api_info():
        return jsonify(info() if info else {})

    @app.post("/api/open/<what>")
    def api_open(what):
        home = os.environ.get("MDGB_HOME")          # impostato solo dall'app per il PC
        if not home or what not in ("folder", "config"):
            abort(404)
        open_path(home if what == "folder" else os.path.join(home, "config.env"), edit=what == "config")
        return jsonify({"ok": True})

    return app


def serve(store, host="127.0.0.1", port=8080, config=None, info=None):
    """Avvia la dashboard in un thread (server di Werkzeug, va bene per la demo)."""
    import logging
    import threading
    from werkzeug.serving import make_server

    logging.getLogger("werkzeug").setLevel(logging.WARNING)       # niente riga di log ogni 2 s
    srv = make_server(host, port, create_app(store, config, info), threaded=True)
    threading.Thread(target=srv.serve_forever, name="dashboard", daemon=True).start()
    return srv
