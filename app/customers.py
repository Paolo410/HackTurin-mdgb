"""Dati per i clienti: chiavi API legate a una zona, con cui scaricare i dati in tempo reale e previsti delle camere
che stanno in quella zona. Escono solo conteggi anonimi: gli stessi che la centrale riceve dai nodi, mai immagini.

API (versione 1), descritta in docs/DATA_API.md:
    GET /api/v1/            cosa offre l'API (senza chiave)
    GET /api/v1/zone        la zona della chiave e le camere che contiene
    GET /api/v1/realtime    ultimi conteggi misurati e stima di adesso
    GET /api/v1/forecast    previsione oraria (?hours=24)
    GET /api/v1/history     conteggi misurati (?hours=24)
    GET /api/v1/metrics     metriche delle ultime 24 ore e verifica della stima
  La chiave va nell'intestazione  X-API-Key: mdgb_...  (oppure  Authorization: Bearer mdgb_...), mai nell'indirizzo.
  ?format=csv su forecast e history per scaricare una tabella.

Gestione delle chiavi, solo dal PC della centrale:
    GET /api/keys, POST /api/keys, DELETE /api/keys/<id>         usati dalla dashboard
    python app/customers.py create --name "Bar Sport" --lat 45.0614 --lon 7.6581 --radius 400 [--days 30]
    python app/customers.py create --name "Comune" --nodes nodo01,nodo02
    python app/customers.py list | revoke <id>
Della chiave si conserva solo l'impronta (SHA-256): la chiave intera si vede una volta, quando viene creata.
"""
import argparse
import csv
import hashlib
import hmac
import io
import json
import math
import secrets
import sqlite3
import threading
import time

SCOPES = ("realtime", "forecast")
MAX_NAME = 80
RADIUS_M = (50, 20000)
RATE_PER_MINUTE = 120
MAX_HOURS = 24
LOCAL = ("127.0.0.1", "::1")
NO_CAMERAS = "Nessuna camera MDGB in questa zona: i dati compariranno quando ne verrà installata una."
MODEL_NOTICE = ("Stime e previsioni vengono da un modello addestrato su uno storico simulato e corretto con i conteggi "
                "delle camere: sono indicative.")


def iso(ts):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def distance_m(lat1, lon1, lat2, lon2):
    """Distanza sulla sfera (formula dell'emisenoverso), in metri."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371000.0 * math.asin(math.sqrt(a))


def check_zone(zone):
    """Zona valida -> la stessa in forma normale: {"lat", "lon", "radius_m"} oppure {"nodes": [...]}. Altrimenti ValueError."""
    if not isinstance(zone, dict):
        raise ValueError("zona mancante")
    if zone.get("nodes"):
        nodes = zone["nodes"]
        if not isinstance(nodes, list) or not all(isinstance(n, str) and n for n in nodes):
            raise ValueError("nodes: elenco di nomi di nodo")
        return {"nodes": sorted(set(nodes))}
    try:
        lat, lon, radius = float(zone["lat"]), float(zone["lon"]), float(zone["radius_m"])
    except (KeyError, TypeError, ValueError):
        raise ValueError("zona: servono lat, lon e radius_m (oppure nodes)")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise ValueError("coordinate fuori dalla Terra")
    if not RADIUS_M[0] <= radius <= RADIUS_M[1]:
        raise ValueError("raggio tra %d e %d metri" % RADIUS_M)
    return {"lat": round(lat, 6), "lon": round(lon, 6), "radius_m": round(radius)}


def cameras_in(zone, cameras):
    """Camere della zona, dalla più vicina al centro: [{"id", "name", "lat", "lon", "distance_m"}]."""
    out = []
    for node, cam in cameras.items():
        lat, lon = cam.get("lat"), cam.get("lon")
        if "nodes" in zone:
            if node in zone["nodes"]:
                out.append({"id": node, "name": cam.get("name", ""), "lat": lat, "lon": lon, "distance_m": None})
        elif lat is not None and lon is not None:
            d = distance_m(zone["lat"], zone["lon"], lat, lon)
            if d <= zone["radius_m"]:
                out.append({"id": node, "name": cam.get("name", ""), "lat": lat, "lon": lon, "distance_m": round(d)})
    return sorted(out, key=lambda c: (c["distance_m"] or 0, c["id"]))


class KeyStore:
    """Chiavi dei clienti nel database della centrale (tabelle api_keys e api_usage)."""

    def __init__(self, db, lock=None):
        self.db, self.lock = db, lock or threading.Lock()
        with self.lock:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS api_keys(
                    id TEXT PRIMARY KEY, name TEXT, key_hash TEXT, zone TEXT, scopes TEXT,
                    created REAL, expires REAL, revoked REAL);
                CREATE TABLE IF NOT EXISTS api_usage(
                    key_id TEXT, day TEXT, endpoint TEXT, requests INTEGER, last REAL,
                    PRIMARY KEY(key_id, day, endpoint));
            """)

    @staticmethod
    def _hash(key):
        return hashlib.sha256(key.encode()).hexdigest()

    def create(self, name, zone, scopes=SCOPES, days=None, now=None):
        """-> {"id", "key", ...}: la chiave intera è solo qui, nel database resta la sua impronta."""
        now = time.time() if now is None else now
        name = " ".join(str(name or "").split())
        if not name or len(name) > MAX_NAME:
            raise ValueError("nome del cliente: da 1 a %d caratteri" % MAX_NAME)
        zone = check_zone(zone)
        scopes = [s for s in SCOPES if s in (scopes or ())]
        if not scopes:
            raise ValueError("almeno un tipo di dati tra: %s" % ", ".join(SCOPES))
        if days is not None and not 0 < float(days) <= 3650:
            raise ValueError("durata in giorni tra 1 e 3650")
        key_id = secrets.token_hex(4)
        key = "mdgb_%s_%s" % (key_id, secrets.token_urlsafe(24))
        expires = None if days is None else now + float(days) * 86400
        with self.lock:
            self.db.execute("INSERT INTO api_keys VALUES(?,?,?,?,?,?,?,NULL)",
                            (key_id, name, self._hash(key), json.dumps(zone), ",".join(scopes), now, expires))
        return {"id": key_id, "key": key, "name": name, "zone": zone, "scopes": scopes, "created": now, "expires": expires}

    def revoke(self, key_id, now=None):
        with self.lock:
            return self.db.execute("UPDATE api_keys SET revoked=? WHERE id=? AND revoked IS NULL",
                                   (time.time() if now is None else now, key_id)).rowcount == 1

    def check(self, presented, now=None):
        """Chiave presentata dal cliente -> (chiave, None) se vale, altrimenti (None, motivo)."""
        now = time.time() if now is None else now
        parts = (presented or "").split("_")
        if len(parts) < 3 or parts[0] != "mdgb":
            return None, "chiave mancante o malformata"
        with self.lock:
            row = self.db.execute("SELECT id, name, key_hash, zone, scopes, created, expires, revoked FROM api_keys "
                                  "WHERE id=?", (parts[1],)).fetchone()
        if row is None or not hmac.compare_digest(row[2], self._hash(presented)):
            return None, "chiave sconosciuta"
        if row[7] is not None:
            return None, "chiave revocata"
        if row[6] is not None and now >= row[6]:
            return None, "chiave scaduta"
        return {"id": row[0], "name": row[1], "zone": json.loads(row[3]), "scopes": row[4].split(","),
                "created": row[5], "expires": row[6]}, None

    def count(self, key_id, endpoint, now=None):
        """Segna una richiesta servita: serve a sapere quanto un cliente usa i dati."""
        now = time.time() if now is None else now
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        with self.lock:
            self.db.execute("INSERT INTO api_usage VALUES(?,?,?,1,?) ON CONFLICT(key_id, day, endpoint) "
                            "DO UPDATE SET requests=requests+1, last=excluded.last", (key_id, day, endpoint, now))

    def list(self, now=None):
        """Tutte le chiavi con il loro uso, senza impronte: [{"id", "name", "zone", ..., "requests_today"}]."""
        now = time.time() if now is None else now
        day = time.strftime("%Y-%m-%d", time.gmtime(now))
        with self.lock:
            keys = self.db.execute("SELECT id, name, zone, scopes, created, expires, revoked FROM api_keys "
                                   "ORDER BY created DESC").fetchall()
            usage = {r[0]: r[1:] for r in self.db.execute(
                "SELECT key_id, SUM(requests), SUM(CASE WHEN day=? THEN requests ELSE 0 END), MAX(last) "
                "FROM api_usage GROUP BY key_id", (day,))}
        out = []
        for key_id, name, zone, scopes, created, expires, revoked in keys:
            total, today, last = usage.get(key_id, (0, 0, None))
            state = "revoked" if revoked is not None else "expired" if expires is not None and now >= expires else "active"
            out.append({"id": key_id, "name": name, "zone": json.loads(zone), "scopes": scopes.split(","),
                        "created": created, "expires": expires, "revoked": revoked, "state": state,
                        "requests_total": total, "requests_today": today, "last_used": last})
        return out


class RateLimit:
    """Al massimo `per_minute` richieste al minuto per chiave (conteggio in memoria, minuto per minuto)."""

    def __init__(self, per_minute=RATE_PER_MINUTE, clock=None):
        self.per_minute, self.clock, self.lock, self.seen = per_minute, clock or time.time, threading.Lock(), {}

    def allow(self, key_id):
        minute = int(self.clock() // 60)
        with self.lock:
            start, n = self.seen.get(key_id, (minute, 0))
            n = n + 1 if start == minute else 1
            self.seen[key_id] = (minute, n)
            return n <= self.per_minute


# ---------------------------------------------------------------- risposte per il cliente
COUNTS = ("ped_in", "ped_out", "cyclist", "vehicles")


def _per_hour(estimate, window_s):
    k = 3600.0 / window_s
    return {c: {"mean": round(estimate[c]["mean"] * k, 1), "low": round(estimate[c]["lo"] * k, 1),
                "high": round(estimate[c]["hi"] * k, 1)} for c in COUNTS}


def realtime(cameras, flow, windows_of, now):
    out, total = [], dict.fromkeys(COUNTS, 0.0)
    for cam in cameras:
        f, ws = flow(cam["id"]), windows_of(cam["id"], 96)
        last = ws[-1] if ws else None
        hour = [w for w in ws if w["t1"] > now - 3600]
        item = dict(cam, last_data_s=None if last is None else round(max(0.0, now - last["t1"])),
                    last_window=None if last is None else dict({c: last[c] for c in COUNTS}, t0=last["t0"], t1=last["t1"],
                                                               t0_iso=iso(last["t0"]), provisional=bool(last["provisional"])),
                    last_hour={c: sum(w[c] for w in hour) for c in COUNTS} if hour else None,
                    estimate_per_hour=None, estimate_from=None)
        if f.get("available"):
            item["estimate_per_hour"] = _per_hour(f["estimate"], f["window_s"])
            item["estimate_from"] = "model_and_counts" if f["mode"] == "fused" else "model_only"
            for c in COUNTS:
                total[c] += item["estimate_per_hour"][c]["mean"]
        out.append(item)
    return {"cameras": out, "zone_estimate_per_hour": {c: round(v, 1) for c, v in total.items()} if out else None}


def forecast(cameras, flow, hours):
    out, zone = [], {}
    for cam in cameras:
        f = flow(cam["id"])
        rows = []
        if f.get("available"):
            for o in f["outlook"][1:hours + 1]:
                rows.append(dict({c: o[c] for c in COUNTS}, t0=o["t0"], t1=o["t1"], t0_iso=iso(o["t0"])))
                z = zone.setdefault(o["t0"], dict(dict.fromkeys(COUNTS, 0.0), t0=o["t0"], t1=o["t1"], t0_iso=iso(o["t0"])))
                for c in COUNTS:
                    z[c] = round(z[c] + o[c], 1)
        out.append(dict(cam, hours=rows))
    return {"cameras": out, "zone_hours": [zone[t] for t in sorted(zone)]}


def history(cameras, windows_of, hours, now):
    out = []
    for cam in cameras:
        ws = [w for w in windows_of(cam["id"], 1440) if w["t1"] > now - hours * 3600]
        out.append(dict(cam, windows=[dict({c: w[c] for c in COUNTS}, t0=w["t0"], t1=w["t1"], t0_iso=iso(w["t0"]),
                                           provisional=bool(w["provisional"])) for w in ws]))
    return {"cameras": out}


def as_csv(cameras, rows_key):
    """Una riga per camera e intervallo: per chi apre i dati in un foglio di calcolo."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["camera", "name", "t0", "t0_iso", "t1"] + list(COUNTS) + (["provisional"] if rows_key == "windows" else []))
    for cam in cameras:
        for r in cam[rows_key]:
            w.writerow([cam["id"], cam["name"], r["t0"], r["t0_iso"], r["t1"]] + [r[c] for c in COUNTS]
                       + ([int(r["provisional"])] if rows_key == "windows" else []))
    return buf.getvalue()


def blueprint(keys, flow, limiter=None):
    """Le pagine dell'API e della gestione delle chiavi. flow: dashboard.Flow (camere, stime, finestre, metriche)."""
    from flask import Blueprint, Response, jsonify, request

    bp = Blueprint("customers", __name__)
    limiter = limiter or RateLimit()

    def fail(status, message, **extra):
        r = jsonify(dict({"error": message}, **extra))
        r.status_code = status
        return r

    def customer(scope, endpoint):
        """-> (chiave, camere della sua zona, None) oppure (None, None, risposta di errore)."""
        presented = request.headers.get("X-API-Key") or ""
        auth = request.headers.get("Authorization", "")
        if not presented and auth.lower().startswith("bearer "):
            presented = auth[7:].strip()
        key, why = keys.check(presented)
        if key is None:
            return None, None, fail(401, why)
        if scope and scope not in key["scopes"]:
            return None, None, fail(403, "questa chiave non comprende i dati '%s'" % scope)
        if not limiter.allow(key["id"]):
            r = fail(429, "troppe richieste: al massimo %d al minuto" % limiter.per_minute)
            r.headers["Retry-After"] = "60"
            return None, None, r
        keys.count(key["id"], endpoint)
        return key, cameras_in(key["zone"], flow.cameras()), None

    def answer(key, cams, body):
        base = {"zone": key["zone"], "available": bool(cams), "generated_at": time.time(),
                "generated_at_iso": iso(time.time())}
        if not cams:
            base["notice"] = NO_CAMERAS
        return dict(base, **body)

    def hours_asked():
        try:
            return max(1, min(MAX_HOURS, int(request.args.get("hours", MAX_HOURS))))
        except ValueError:
            return MAX_HOURS

    def table(cams, rows_key, name):
        return Response(as_csv(cams, rows_key), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=mdgb-%s.csv" % name})

    @bp.get("/api/v1/")
    def index():
        return jsonify({"service": "MDGB, dati degli attraversamenti pedonali", "version": 1,
                        "authentication": "intestazione X-API-Key (oppure Authorization: Bearer)",
                        "endpoints": {"/api/v1/zone": "la zona della chiave e le camere che contiene",
                                      "/api/v1/realtime": "ultimi conteggi e stima di adesso",
                                      "/api/v1/forecast": "previsione oraria, ?hours=1..24, ?format=csv",
                                      "/api/v1/history": "conteggi misurati, ?hours=1..24, ?format=csv",
                                      "/api/v1/metrics": "metriche delle ultime 24 ore"},
                        "data": "solo conteggi anonimi per attraversamento: nessuna immagine, nessun dato personale"})

    @bp.get("/api/v1/zone")
    def zone():
        key, cams, error = customer(None, "zone")
        return error or jsonify(answer(key, cams, {"customer": key["name"], "scopes": key["scopes"],
                                                    "expires": key["expires"], "cameras": cams}))

    @bp.get("/api/v1/realtime")
    def api_realtime():
        key, cams, error = customer("realtime", "realtime")
        if error:
            return error
        return jsonify(answer(key, cams, dict(realtime(cams, flow.node, flow.windows, time.time()), notice_model=MODEL_NOTICE)))

    @bp.get("/api/v1/forecast")
    def api_forecast():
        key, cams, error = customer("forecast", "forecast")
        if error:
            return error
        body = forecast(cams, flow.node, hours_asked())
        if request.args.get("format") == "csv":
            return table(body["cameras"], "hours", "forecast")
        return jsonify(answer(key, cams, dict(body, notice_model=MODEL_NOTICE)))

    @bp.get("/api/v1/history")
    def api_history():
        key, cams, error = customer("realtime", "history")
        if error:
            return error
        body = history(cams, flow.windows, hours_asked(), time.time())
        if request.args.get("format") == "csv":
            return table(body["cameras"], "windows", "history")
        return jsonify(answer(key, cams, body))

    @bp.get("/api/v1/metrics")
    def api_metrics():
        key, cams, error = customer("realtime", "metrics")
        if error:
            return error
        items = [dict(cam, metrics=flow.analytics(cam["id"]), estimate_check=flow.node(cam["id"]).get("quality"))
                 for cam in cams]
        return jsonify(answer(key, cams, {"cameras": items}))

    # ---- gestione delle chiavi: solo da questo PC (la dashboard può essere aperta alla rete locale, questo no)
    def local_only():
        return None if request.remote_addr in LOCAL else fail(403, "le chiavi si gestiscono solo dal PC della centrale")

    @bp.get("/api/keys")
    def keys_list():
        return local_only() or jsonify({"keys": [dict(k, cameras=[c["id"] for c in cameras_in(k["zone"], flow.cameras())])
                                                  for k in keys.list()], "scopes": list(SCOPES)})

    @bp.post("/api/keys")
    def keys_create():
        denied = local_only()
        if denied:
            return denied
        body = request.get_json(silent=True) or {}
        try:
            made = keys.create(body.get("name"), body.get("zone"), body.get("scopes") or SCOPES, body.get("days"))
        except ValueError as e:
            return fail(400, str(e))
        return jsonify(dict(made, cameras=[c["id"] for c in cameras_in(made["zone"], flow.cameras())]))

    @bp.delete("/api/keys/<key_id>")
    def keys_revoke(key_id):
        return local_only() or (jsonify({"revoked": True}) if keys.revoke(key_id) else fail(404, "chiave non trovata o già revocata"))

    return bp


def main(argv=None):
    import os
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("INGEST_DB") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "central.db"),
                    help="database della centrale (nell'app: central.db nella cartella delle impostazioni)")
    sub = ap.add_subparsers(dest="command", required=True)
    c = sub.add_parser("create", help="crea una chiave e la mostra (una volta sola)")
    c.add_argument("--name", required=True)
    c.add_argument("--lat", type=float)
    c.add_argument("--lon", type=float)
    c.add_argument("--radius", type=float, default=500, help="raggio della zona in metri")
    c.add_argument("--nodes", help="in alternativa a lat/lon: nodi separati da virgola")
    c.add_argument("--scopes", default=",".join(SCOPES))
    c.add_argument("--days", type=float, help="durata; senza, la chiave non scade")
    sub.add_parser("list", help="elenca le chiavi e il loro uso")
    r = sub.add_parser("revoke", help="revoca una chiave")
    r.add_argument("id")
    a = ap.parse_args(argv)
    keys = KeyStore(sqlite3.connect(a.db, isolation_level=None))
    if a.command == "create":
        zone = {"nodes": a.nodes.split(",")} if a.nodes else {"lat": a.lat, "lon": a.lon, "radius_m": a.radius}
        try:
            made = keys.create(a.name, zone, a.scopes.split(","), a.days)
        except ValueError as e:
            raise SystemExit("chiave non creata: %s" % e)
        print("Chiave per %s (id %s). Si vede solo adesso, consegnala al cliente:\n\n    %s\n" % (made["name"], made["id"], made["key"]))
    elif a.command == "list":
        for k in keys.list():
            print("%s  %-9s %-24s %s  richieste: %d (oggi %d)" % (k["id"], k["state"], k["name"][:24], json.dumps(k["zone"]),
                                                                    k["requests_total"], k["requests_today"]))
    else:
        print("revocata" if keys.revoke(a.id) else "chiave non trovata o già revocata")


if __name__ == "__main__":
    main()
