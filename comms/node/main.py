"""Nodo crosswalk: orchestrazione.

  sorgente eventi ──► on_crossing ──► 1) Outbox (eMMC)            ← SEMPRE per primo
                                  └─► 2) MCU: estensione verde      ← locale, funziona offline
  loop ogni 0,2 s:
      uplink.pump()        outbox ──MQTT/TCP──► broker   (backfill automatico quando torna la rete)
      aggregator.tick()    online: MQTT `agg` | offline: 28 byte ──Bridge──► MCU ──► LoRa
      heartbeat all'MCU    (watchdog: se Linux tace, l'MCU lo segnala via LoRa)
"""
import logging
import os
import time

import config as cfg
from aggregator import Aggregator
from backup_link import ON_UNO_Q, make_backup, make_mcu
from event_source import make_source
from outbox import Outbox
from payload import SLOW_USERS, cat_id
from uplink_mqtt import MqttUplink

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)-7s %(levelname)-7s %(message)s")
log = logging.getLogger("main")


class Node:
    def __init__(self):
        self.ob = Outbox(cfg.DB_PATH)
        self.mcu = make_mcu()
        self.up = MqttUplink(self.ob, cfg.NODE_ID, cfg.TOPIC_PREFIX, cfg.MQTT_HOST, cfg.MQTT_PORT,
                             cfg.MQTT_TLS, cfg.MQTT_USER, cfg.MQTT_PASS,
                             cfg.MQTT_BATCH, cfg.MQTT_ACK_TIMEOUT_S,
                             cfg.MQTT_CA, cfg.MQTT_CERT, cfg.MQTT_KEY, cfg.MQTT_SESSION_EXPIRY_S)
        self.backup = make_backup(cfg.BACKUP_LINK, self.mcu, cfg.BLE_SUDO)
        self.agg = Aggregator(self.ob, self.up, self.backup, cfg.AGG_PERIOD_S, os.path.dirname(cfg.DB_PATH))
        self.source = make_source(cfg.EVENT_SOURCE, cfg.SIM_RATE_HZ)
        self._t_beat = self._t_status = self._t_prune = 0.0
        log.info("nodo %s | UNO Q=%s | broker %s:%d | backup=%s | backlog iniziale %d",
                 cfg.NODE_ID, ON_UNO_Q, cfg.MQTT_HOST, cfg.MQTT_PORT, cfg.BACKUP_LINK, self.ob.backlog())

    # chiamata dalla sorgente (thread della camera / simulatore)
    def on_crossing(self, label, direction, conf):
        ts = time.time()
        seq = self.ob.put(ts, cat_id(label), int(direction), float(conf))   # 1) persistenza
        if label in SLOW_USERS:                                              # 2) azione locale
            self.mcu.pedestrian_alert(cfg.ALERT_SECONDS)
            self.up.publish("alert", {"seq": seq, "ts": ts, "cat": label, "dir": direction}, qos=1)
        log.debug("evento #%d %s dir=%d", seq, label, direction)

    def start(self):
        self.source.start(self.on_crossing)

    def loop_once(self):
        now = time.time()
        self.up.pump()
        self.agg.tick(now)
        if now - self._t_beat >= cfg.HEARTBEAT_S:
            self.mcu.heartbeat()
            self._t_beat = now
        if now - self._t_status >= 10:
            backlog = self.ob.backlog()
            self.up.publish("status", {"online": True, "ts": now, "backlog": backlog}, retain=True)
            log.info("rete=%s backlog=%d", "ONLINE" if self.up.online() else "OFFLINE", backlog)
            self._t_status = now
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
