"""Canale primario: MQTT 5 su TCP (porta 1883) o TCP+TLS (porta 8883 / 443).

Demo: broker Mosquitto dentro l'app della centrale sul PC (rete locale, senza TLS). Produzione: un broker MQTT 5 in
cloud con TLS e un certificato per nodo (mutual TLS); QoS 1, Last Will, messaggi retained, sessione persistente.

- Svuota l'outbox a batch (un batch "in volo" alla volta), formato C4 `events` di docs/CONTRACTS.md v1.
- QoS 1: solo un PUBACK POSITIVO (reason code < 0x80) marca gli eventi come inviati. Con un PUBACK negativo
  gli eventi restano in coda e si riprova con un'attesa crescente (fino a nack_backoff_max_s).
- "online" = connesso E almeno un PUBACK positivo negli ultimi ack_window_s secondi (non basta il TCP).
  L'heartbeat `hb` (QoS 1, ogni 10 s) garantisce conferme anche quando non ci sono eventi.
- Se la connessione cade, gli eventi in volo restano "non inviati" e verranno rispediti:
  possono nascere duplicati, che il backend elimina grazie a (node_id, seq).
- Last Will su `hb`: se il nodo sparisce, il broker pubblica da solo online = false.
"""
import json
import logging
import ssl
import threading
import time

import paho.mqtt.client as mqtt

from payload import C4_VERSION, event_id

log = logging.getLogger("uplink")


def make_tls_context(ca="", cert="", key=""):
    """TLS verso un broker in cloud; con cert e key anche autenticazione del nodo (mutual TLS)."""
    ctx = ssl.create_default_context(cafile=ca or None)
    if cert and key:
        ctx.load_cert_chain(certfile=cert, keyfile=key)
    return ctx


class MqttUplink:
    def __init__(self, outbox, node_id, prefix, host, port, tls=False, user="", password="",
                 batch=50, ack_timeout_s=30, ca="", cert="", key="", session_expiry_s=3600,
                 ack_window_s=30, nack_backoff_max_s=60, hb_provider=None):
        self.ob = outbox
        self.node = node_id
        self.base = f"{prefix}/{node_id}"
        self.batch = batch
        self.ack_timeout_s = ack_timeout_s
        self.ack_window_s = ack_window_s
        self.nack_backoff_max_s = nack_backoff_max_s
        self.hb_provider = hb_provider or (lambda: {"v": C4_VERSION, "node_id": node_id, "type": "hb",
                                                    "ts": time.time(), "online": True})
        self._lock = threading.Lock()
        self._inflight = {}            # mid -> (lista seq, istante di invio)
        self._publishing = False       # pump() sta pubblicando un batch (fuori dal lock, vedi pump)
        self._early = {}               # mid -> reason code dei PUBACK arrivati prima che pump() registrasse il batch
        self.last_ack = 0.0            # ultimo PUBACK positivo (qualsiasi messaggio QoS 1)
        self.ok_since = None           # primo PUBACK positivo dopo l'ultimo problema (per l'isteresi)
        self.nacks = 0                 # PUBACK negativi ricevuti
        self._nack_wait = 0.0
        self._hold_until = 0.0         # dopo un PUBACK negativo non si rispedisce prima di questo istante

        self.c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=node_id, protocol=mqtt.MQTTv5)
        if user:
            self.c.username_pw_set(user, password)
        if tls:
            self.c.tls_set_context(make_tls_context(ca, cert, key))
        self.c.will_set(f"{self.base}/hb", json.dumps({"v": C4_VERSION, "node_id": node_id, "type": "hb",
                                                       "online": False}), qos=1, retain=True)
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
        try:
            hb = self.hb_provider()
        except Exception:                 # mai far cadere il thread di rete di paho
            log.exception("hb_provider fallito")
            hb = {"v": C4_VERSION, "node_id": self.node, "type": "hb", "ts": time.time(), "online": True}
        c.publish(f"{self.base}/hb", json.dumps(hb, separators=(",", ":")), qos=1, retain=True)

    def _on_disconnect(self, c, userdata, flags, reason_code, props):
        log.warning("MQTT disconnesso (%s) -> modalità offline, gli eventi restano nell'outbox", reason_code)
        with self._lock:
            self._inflight.clear()
            self.ok_since = None

    def _on_publish(self, c, userdata, mid, reason_code, props):
        now = time.time()
        with self._lock:
            item = self._inflight.pop(mid, None)
            if item is None and self._publishing:
                self._early[mid] = reason_code
            if reason_code.is_failure:                    # es. 0x87 Not authorized, 0x97 Quota exceeded
                self.nacks += 1
                self.ok_since = None
                self._nack_wait = min(max(1.0, 2 * self._nack_wait), self.nack_backoff_max_s)
                self._hold_until = now + self._nack_wait
            else:                                         # 0x00 Success, 0x10 No matching subscribers
                self.last_ack = now
                self._nack_wait = 0.0
                if self.ok_since is None:
                    self.ok_since = now
        if reason_code.is_failure:
            log.warning("PUBACK negativo (%s)%s: restano in coda, riprovo tra %.0f s", reason_code,
                        f" per {len(item[0])} eventi" if item else "", self._nack_wait)
        elif item:
            self.ob.ack(item[0])

    # ---------- API ----------
    def connected(self) -> bool:
        return self.c.is_connected()

    def online(self, now=None) -> bool:
        """Canale sano: connesso e un PUBACK positivo negli ultimi ack_window_s secondi."""
        now = time.time() if now is None else now
        return self.connected() and now - self.last_ack <= self.ack_window_s

    def stable_s(self, now=None) -> float:
        """Da quanti secondi il canale è sano senza interruzioni né PUBACK negativi (0 se non è sano)."""
        now = time.time() if now is None else now
        ok_since = self.ok_since
        return now - ok_since if ok_since is not None and self.online(now) else 0.0

    def pump(self) -> int:
        """Invia il prossimo batch di eventi in coda. Ritorna quanti eventi ha messo in volo."""
        if not self.connected():
            return 0
        with self._lock:
            now = time.time()
            if self._inflight:
                mid, (seqs, t_sent) = next(iter(self._inflight.items()))
                if now - t_sent < self.ack_timeout_s:
                    return 0
                log.warning("ACK non ricevuto per %d eventi: verranno rispediti", len(seqs))
                self._inflight.clear()
                self.ok_since = None
            if now < self._hold_until:
                return 0
            rows = self.ob.pending(self.batch)
            if not rows:
                return 0
            self._publishing = True
        seqs = [r[0] for r in rows]
        msg = {"v": C4_VERSION, "node_id": self.node,
               "events": [dict({"seq": seq, "event_id": event_id(self.node, seq)}, **json.loads(body))
                          for seq, body in rows]}
        # publish() SENZA self._lock: il thread di rete di paho chiama _on_publish tenendo il proprio mutex
        # e poi prende self._lock; pubblicare col lock in mano causerebbe un deadlock (blocco dell'invio).
        info, rc = None, None
        try:
            info = self.c.publish(f"{self.base}/events", json.dumps(msg, separators=(",", ":")), qos=1)
        finally:
            with self._lock:                        # tutto insieme: nessun PUBACK può cadere "in mezzo"
                self._publishing = False
                early, self._early = self._early, {}
                if info is not None and info.rc == mqtt.MQTT_ERR_SUCCESS:
                    rc = early.get(info.mid)
                    if rc is None:                  # caso normale: il PUBACK arriverà dopo
                        self._inflight[info.mid] = (seqs, time.time())
        if info.rc != mqtt.MQTT_ERR_SUCCESS:
            return 0
        if rc is not None and not rc.is_failure:    # PUBACK positivo arrivato prima della registrazione
            self.ob.ack(seqs)
        return len(rows)

    def publish(self, sub_topic: str, obj, qos=1, retain=False) -> bool:
        if not self.connected():
            return False
        info = self.c.publish(f"{self.base}/{sub_topic}", json.dumps(obj, separators=(",", ":")),
                              qos=qos, retain=retain)
        return info.rc == mqtt.MQTT_ERR_SUCCESS

    def stop(self):
        self.c.loop_stop()
        self.c.disconnect()
