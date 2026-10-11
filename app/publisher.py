"""La centrale pubblica su MQTT, per ogni camera, la stima del flusso e le metriche (docs/DATA_API.md):

    {prefix}/<nodo>/forecast     stima di adesso e previsione delle prossime 24 ore (modello di ai/forecast)
    {prefix}/<nodo>/analytics    metriche delle ultime 24 ore: traffico per ora, sicurezza, verifica della stima

Messaggi JSON con "v", QoS 1, retained: chi si collega riceve subito l'ultimo valore. Gli argomenti sono diversi da
quelli che la centrale ascolta (events, agg, hb, backup), quindi non rientrano nell'ingest.
"""
import json
import logging
import time

log = logging.getLogger("publisher")
VERSION = 1
COUNTS = ("ped_in", "ped_out", "cyclist", "vehicles")


def forecast_message(node, f, now=None):
    """Stima di una camera (risposta di Forecaster.forecast) -> messaggio compatto, in conteggi all'ora."""
    per_hour = 3600.0 / f["window_s"]
    return {"v": VERSION, "node_id": node, "type": "forecast", "ts": round(f["now"] if now is None else now, 1),
            "from": "model_and_counts" if f["mode"] == "fused" else "model_only",
            "now": {c: {"mean": round(f["estimate"][c]["mean"] * per_hour, 1), "low": round(f["estimate"][c]["lo"] * per_hour, 1),
                        "high": round(f["estimate"][c]["hi"] * per_hour, 1)} for c in COUNTS},
            "hours": [dict({c: o[c] for c in COUNTS}, t0=o["t0"]) for o in f["outlook"][1:]],
            "anomaly": f["anomaly"], "model": {"trained_on": f["model"].get("trained_on")}}


def analytics_message(node, analytics, quality, now=None):
    return {"v": VERSION, "node_id": node, "type": "analytics", "ts": round(analytics["now"] if now is None else now, 1),
            "traffic": analytics["traffic"], "safety": analytics["safety"], "estimate_check": quality}


def publish(client, flow, prefix="mdgb"):
    """Pubblica i due messaggi di ogni camera. Ritorna quanti ne ha affidati al client MQTT."""
    sent = 0
    for node in flow.nodes():
        f = flow.node(node)
        if not f.get("available"):
            continue
        messages = {"forecast": forecast_message(node, f)}
        a = flow.analytics(node)
        if a.get("available", True):
            messages["analytics"] = analytics_message(node, a, f.get("quality"))
        for kind, msg in messages.items():
            try:
                client.publish("%s/%s/%s" % (prefix, node, kind), json.dumps(msg, separators=(",", ":")), qos=1, retain=True)
                sent += 1
            except Exception as e:                       # il broker può cadere in ogni momento: si riprova al prossimo giro
                log.warning("pubblicazione di %s/%s fallita: %s", node, kind, e)
    return sent


class Publisher:
    """Chiama publish() ogni `period_s` secondi, quando il client è collegato. tick() si chiama spesso: decide lei."""

    def __init__(self, client, flow, prefix="mdgb", period_s=30, clock=time.time):
        self.client, self.flow, self.prefix, self.period_s, self.clock = client, flow, prefix, period_s, clock
        self.last, self.sent = None, 0

    def tick(self):
        now = self.clock()
        if self.period_s <= 0 or (self.last is not None and now - self.last < self.period_s):
            return 0
        if not self.client.is_connected():
            return 0
        self.last = now
        n = publish(self.client, self.flow, self.prefix)
        self.sent += n
        return n
