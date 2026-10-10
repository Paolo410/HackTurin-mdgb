"""Nodo MDGB, parte comunicazione: orchestrazione (docs/CONTRACTS.md v1).

  file C3/C5 (o simulatore) ──► Outbox (eMMC)        ← SEMPRE per primo
  loop ogni 0,2 s:
      uplink.pump()        outbox ──MQTT──► broker (sul PC nella demo)   (backfill automatico quando torna la rete)
      aggregator.tick()    MQTT `agg` (finestre esatte, anche quelle maturate durante un blackout)
      failover.tick()      30 s senza conferme MQTT -> backup ACCESO (BLE nella demo, LoRa in produzione):
                           HB + AGG subito, poi HB periodico, AGG a ogni finestra, allarmi subito;
                           60 s di MQTT stabile -> backup SPENTO
      hb ogni 10 s         MQTT `hb` retained (+ Last Will): dà conferme anche senza eventi
La sicurezza non passa da qui: il semaforo lo comanda ai/ tramite comms/actuators.py e il firmware.
"""
import logging
import os
import shutil
import time

import config as cfg
from aggregator import Aggregator
from backup_link import ON_UNO_Q, make_backup, make_mcu
from event_source import make_source
from failover import Failover
from outbox import Outbox
from payload import C4_VERSION
from uplink_mqtt import MqttUplink

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-7s %(levelname)-7s %(message)s")
log = logging.getLogger("main")


def disk_free_pct(path):
    try:
        du = shutil.disk_usage(os.path.dirname(path) or ".")
        return 100 * du.free / du.total
    except OSError:
        return 0


class NodeState:
    """Ultime righe `status` (C3) ed `env`/`failsafe` (C5): alimentano `hb` e `agg`."""

    AI_SILENT_S = 15          # nessuno `status` da ai/ per 15 s -> mode degraded

    def __init__(self):
        self.status, self.env, self.batt = None, {}, None
        self.t_status, self.t_failsafe = 0.0, 0.0

    def on_info(self, obj):
        t = obj.get("type")
        if t == "status":
            self.status, self.t_status = obj, time.time()
        elif t == "env":
            self.env = {k: obj[k] for k in ("t_c", "rh", "lux") if k in obj}
            self.batt = obj.get("batt", self.batt)

    def on_event(self, ev):
        if ev.get("type") == "failsafe":
            self.t_failsafe = time.time()

    def mode(self, now=None):
        now = time.time() if now is None else now
        if self.t_failsafe > self.t_status:
            return "failsafe"
        if now - self.t_status > self.AI_SILENT_S or (self.status or {}).get("state") == "DEGRADED":
            return "degraded"
        return "normal"


class Node:
    def __init__(self):
        self.ob = Outbox(cfg.DB_PATH)
        self.mcu = make_mcu()
        self.state = NodeState()
        self.backup = make_backup(cfg.BACKUP_LINK, self.mcu, cfg.BLE_SUDO)
        self.up = MqttUplink(self.ob, cfg.NODE_ID, cfg.TOPIC_PREFIX, cfg.MQTT_HOST, cfg.MQTT_PORT,
                             cfg.MQTT_TLS, cfg.MQTT_USER, cfg.MQTT_PASS,
                             cfg.MQTT_BATCH, cfg.MQTT_ACK_TIMEOUT_S,
                             cfg.MQTT_CA, cfg.MQTT_CERT, cfg.MQTT_KEY, cfg.MQTT_SESSION_EXPIRY_S,
                             cfg.MQTT_ACK_WINDOW_S, cfg.MQTT_NACK_BACKOFF_MAX_S, hb_provider=self.hb)
        self.agg = Aggregator(self.ob, self.up, cfg.AGG_PERIOD_S, cfg.NODE_ID, self.state)
        self.failover = Failover(self.ob, self.up, self.backup, self.agg, self.state,
                                 cfg.BACKUP_ON_AFTER_S, cfg.BACKUP_OFF_AFTER_S, cfg.BACKUP_HB_S,
                                 disk_free=lambda: disk_free_pct(cfg.DB_PATH))
        self.source = make_source(cfg.EVENT_SOURCE, cfg.SIM_RATE_HZ, cfg.C3_DIR, self.ob)
        self._t_hb = self._t_prune = 0.0
        log.info("nodo %s | UNO Q=%s | broker %s:%d | backup=%s | sorgente=%s | backlog iniziale %d",
                 cfg.NODE_ID, ON_UNO_Q, cfg.MQTT_HOST, cfg.MQTT_PORT, cfg.BACKUP_LINK, cfg.EVENT_SOURCE,
                 self.ob.backlog())

    # chiamata dal simulatore (C3FileSource scrive direttamente nell'outbox, insieme al cursore)
    def on_event(self, ev):
        seq = self.ob.put(ev)                                                # persistenza, sempre per prima
        self.state.on_event(ev)
        log.debug("evento #%d %s", seq, ev.get("type"))

    def hb(self, now=None):
        """Heartbeat C4 `hb`."""
        now = time.time() if now is None else now
        st = self.state.status or {}
        return {"v": C4_VERSION, "node_id": cfg.NODE_ID, "type": "hb", "ts": round(now, 3), "online": True,
                "mode": self.state.mode(now), "state": st.get("state"),
                "backup": self.backup.kind if self.backup.active else "off", "batt": self.state.batt,
                "queue": self.ob.backlog(), "disk_free_pct": round(disk_free_pct(cfg.DB_PATH)), "fps": st.get("fps")}

    def start(self):
        self.source.start(self.on_event, self.state.on_info)

    def loop_once(self):
        now = time.time()
        self.up.pump()
        self.agg.tick(now)
        self.failover.tick(now)
        if now - self._t_hb >= cfg.HB_PERIOD_S:
            hb = self.hb(now)
            self.up.publish("hb", hb, retain=True)
            log.info("rete=%s backlog=%d mode=%s", "ONLINE" if self.up.online(now) else "OFFLINE",
                     hb["queue"], hb["mode"])
            self._t_hb = now
        if now - self._t_prune >= 600:
            n = self.ob.prune(cfg.RETENTION_MAX_ROWS)
            if n:
                log.info("retention: cancellati %d eventi vecchi già inviati", n)
            self._t_prune = now

    def stop(self):
        self.source.stop()
        self.up.stop()


def run():
    node = Node()
    node.start()

    def loop():
        node.loop_once()
        time.sleep(0.2)

    if ON_UNO_Q:
        from arduino.app_utils import App
        App.run(user_loop=loop)
    else:
        try:
            while True:
                loop()
        except KeyboardInterrupt:
            node.stop()


if __name__ == "__main__":
    run()
