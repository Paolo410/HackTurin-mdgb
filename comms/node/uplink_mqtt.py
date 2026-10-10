"""Canale primario: MQTT 5 su TCP (porta 1883) o TCP+TLS (porta 8883 / 443).

Compatibile con AWS IoT Core: autenticazione mutual TLS con certificato X.509, QoS 1 (AWS non
supporta QoS 2), Last Will, messaggi retained e sessione persistente (Session Expiry).

- Svuota l'outbox a batch (un batch "in volo" alla volta).
- QoS 1: il broker risponde con PUBACK -> solo allora gli eventi sono marcati come inviati.
- Se la connessione cade, gli eventi in volo restano "non inviati" e verranno rispediti:
  possono nascere duplicati, che il backend elimina grazie a (node, seq).
- Last Will: se il nodo sparisce, il broker pubblica da solo status = offline.
"""
import json
import logging
import ssl
import threading
import time

import paho.mqtt.client as mqtt

from payload import event_to_json

log = logging.getLogger("uplink")


def make_tls_context(ca="", cert="", key="", alpn_443=False):
    """TLS per AWS IoT Core (o qualsiasi broker con mutual TLS).
    Sulla porta 443 AWS richiede l'ALPN 'x-amzn-mqtt-ca' (utile se la rete blocca la 8883)."""
    ctx = ssl.create_default_context(cafile=ca or None)
    if cert and key:
        ctx.load_cert_chain(certfile=cert, keyfile=key)
    if alpn_443:
        ctx.set_alpn_protocols(["x-amzn-mqtt-ca"])
    return ctx


class MqttUplink:
    def __init__(self, outbox, node_id, prefix, host, port, tls=False, user="", password="",
                 batch=50, ack_timeout_s=30, ca="", cert="", key="", session_expiry_s=3600):
        self.ob = outbox
        self.node = node_id
        self.base = f"{prefix}/{node_id}"
        self.batch = batch
        self.ack_timeout_s = ack_timeout_s
        self._lock = threading.Lock()
        self._inflight = {}            # mid -> (lista seq, istante di invio)

        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=node_id, protocol=mqtt.MQTTv5)
        if user:
            self.c.username_pw_set(user, password)
        if tls:
            self.c.tls_set_context(make_tls_context(ca, cert, key, alpn_443=(port == 443)))
        self.c.will_set(f"{self.base}/status", json.dumps({"online": False}), qos=1, retain=True)
        self.c.on_connect = self._on_connect
        self.c.on_disconnect = self._on_disconnect
        self.c.on_publish = self._on_publish
        self.c.reconnect_delay_set(min_delay=1, max_delay=30)   # backoff esponenziale
        props = mqtt.Properties(mqtt.PacketTypes.CONNECT)
        props.SessionExpiryInterval = session_expiry_s
        self.c.connect_async(host, port, keepalive=30, clean_start=False, properties=props)
        self.c.loop_start()                                     # thread di rete + riconnessione automatica

    # ---------- callback paho ----------
    def _on_connect(self, c, userdata, flags, reason_code, props):
        if reason_code.is_failure:
            log.warning("connessione rifiutata: %s", reason_code)
            return
        log.info("MQTT connesso")
        c.publish(f"{self.base}/status", json.dumps({"online": True, "ts": time.time()}), qos=1, retain=True)

    def _on_disconnect(self, c, userdata, flags, reason_code, props):
        log.warning("MQTT disconnesso (%s) -> modalità offline, gli eventi restano nell'outbox", reason_code)
        with self._lock:
            self._inflight.clear()

    def _on_publish(self, c, userdata, mid, reason_code, props):
        with self._lock:
            item = self._inflight.pop(mid, None)
        if item:
            self.ob.ack(item[0])

    # ---------- API ----------
    def online(self) -> bool:
        return self.c.is_connected()

    def pump(self) -> int:
        """Invia il prossimo batch di eventi in coda. Ritorna quanti eventi ha messo in volo."""
        if not self.online():
            return 0
        with self._lock:
            if self._inflight:
                mid, (seqs, t_sent) = next(iter(self._inflight.items()))
                if time.time() - t_sent < self.ack_timeout_s:
                    return 0
                log.warning("ACK non ricevuto per %d eventi: verranno rispediti", len(seqs))
                self._inflight.clear()
            rows = self.ob.pending(self.batch)
            if not rows:
                return 0
            msg = {"node": self.node, "events": [event_to_json(*r) for r in rows]}
            info = self.c.publish(f"{self.base}/events", json.dumps(msg, separators=(",", ":")), qos=1)
            if info.rc != mqtt.MQTT_ERR_SUCCESS:
                return 0
            self._inflight[info.mid] = ([r[0] for r in rows], time.time())
            return len(rows)

    def publish(self, sub_topic: str, obj, qos=1, retain=False) -> bool:
        if not self.online():
            return False
        info = self.c.publish(f"{self.base}/{sub_topic}", json.dumps(obj, separators=(",", ":")),
                              qos=qos, retain=retain)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def stop(self):
        self.c.loop_stop()
        self.c.disconnect()
