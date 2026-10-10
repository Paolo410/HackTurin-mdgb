"""Failover verso il canale di backup (BLE nella demo, LoRa in produzione) — docs/CONTRACTS.md v1, C4-B.

Quando si accende e si spegne (isteresi: niente salti continui tra i canali):
  - ACCESO  dopo on_after_s (30 s) senza nessun PUBACK positivo (o dall'avvio, se MQTT non è mai partito);
  - SPENTO  dopo off_after_s (60 s) di MQTT stabile (connesso, conferme regolari, nessun PUBACK negativo).
MQTT intanto non si ferma mai: si riconnette e fa il backfill appena può.

Cosa trasmette mentre è acceso (mai i singoli eventi, che restano nello Store & Forward):
  - SUBITO all'accensione: HB + AGG dell'ultima finestra chiusa + gli allarmi non ancora confermati via MQTT;
  - HB ogni hb_period_s (5 min in produzione);
  - AGG a ogni finestra chiusa (15 min in produzione);
  - allarmi (incidente, manomissione, guasto lampada, fail-safe del firmware) appena arrivano, uno ogni alarm_hold_s
    così il ricevitore fa in tempo a vederli prima che il beacon degli allarmi cambi.
"""
import collections
import json
import logging
import time

from payload import TYPE_AGG, TYPE_HB, alarm_to_c4b, pack_agg, pack_hb

log = logging.getLogger("failover")


class Failover:
    def __init__(self, outbox, uplink, backup, aggregator, state=None, on_after_s=30, off_after_s=60,
                 hb_period_s=300, alarm_hold_s=2.0, max_alarms_on_start=5, disk_free=None, clock=time.time):
        self.ob, self.up, self.backup, self.agg, self.state = outbox, uplink, backup, aggregator, state
        self.on_after_s, self.off_after_s = on_after_s, off_after_s
        self.hb_period_s, self.alarm_hold_s = hb_period_s, alarm_hold_s
        self.max_alarms_on_start = max_alarms_on_start
        self.disk_free = disk_free or (lambda: None)
        self._clock = clock
        self.t_boot = clock()
        self.active = False
        self._next_hb = 0.0
        self._last_agg_t0 = None
        self._alarm_seq = 0              # ultimo allarme già passato al backup
        self._alarms = collections.deque()
        self._t_alarm = 0.0
        self._retry_at = 0.0             # dopo un invio fallito (es. btmgmt in errore) si riprova tra 5 s

    def silent_s(self, now=None) -> float:
        """Secondi senza PUBACK positivi (dall'avvio se non ne è mai arrivato uno)."""
        now = self._clock() if now is None else now
        return now - max(self.up.last_ack, self.t_boot)

    def tick(self, now=None):
        now = self._clock() if now is None else now
        if not self.active:
            if self.silent_s(now) < self.on_after_s:
                return
            self._activate(now)
        elif self.up.stable_s(now) >= self.off_after_s:
            self._deactivate(now)
            return
        self._send_due(now)

    # ---------- stati ----------
    def _activate(self, now):
        self.active = True
        log.warning("nessuna conferma MQTT da %.0f s: backup %s ACCESO", self.silent_s(now), self.backup.kind)
        self._next_hb = now                    # primo pacchetto subito
        self._last_agg_t0 = None
        recent = self.ob.unsent_alarms(self._alarm_seq, limit=self.max_alarms_on_start)
        self._alarms.extend(recent)
        if recent:
            self._alarm_seq = recent[-1][0]

    def _deactivate(self, now):
        self.active = False
        self._alarms.clear()
        self.backup.idle()
        log.info("MQTT stabile da %.0f s: backup %s SPENTO", self.up.stable_s(now), self.backup.kind)

    # ---------- trasmissioni ----------
    def _send(self, payload, type_, now):
        ok = self.backup.send(payload, type_)
        if not ok:
            self._retry_at = now + 5
        return ok

    def _send_due(self, now):
        if now < self._retry_at:
            return
        if now >= self._next_hb and self._send(self._hb(now), TYPE_HB, now):
            self._next_hb = now + self.hb_period_s
        last_closed = (int(now) // self.agg.P) * self.agg.P - self.agg.P
        if last_closed != self._last_agg_t0:
            st = self.state
            pkt = pack_agg(self.agg.window_agg(last_closed, now), self.ob.backlog(),
                           batt=st.batt if st else None, degraded=st is not None and st.mode() != "normal")
            if self._send(pkt, TYPE_AGG, now):
                self._last_agg_t0 = last_closed
        new = self.ob.unsent_alarms(self._alarm_seq)
        if new:
            self._alarms.extend(new)
            self._alarm_seq = new[-1][0]
        if self._alarms and now - self._t_alarm >= self.alarm_hold_s:
            seq, body = self._alarms.popleft()
            msg = alarm_to_c4b(json.loads(body))
            if msg is not None and self._send(msg[1], msg[0], now):
                self._t_alarm = now
                log.warning("allarme #%d (%s) sul backup", seq, json.loads(body).get("type"))

    def _hb(self, now):
        st = self.state
        status = (st.status or {}) if st else {}
        return pack_hb(now, mode=st.mode(now) if st else "normal", state=status.get("state"),
                       backlog=self.ob.backlog(), batt=st.batt if st else None, disk_free_pct=self.disk_free(),
                       offline_min=int(self.silent_s(now) // 60))
