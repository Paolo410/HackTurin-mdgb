"""Aggregatore a finestre fisse (es. 15 min) con doppia uscita.

- ONLINE : pubblica su MQTT `agg` in JSON tutte le finestre chiuse e non ancora pubblicate
           (anche quelle maturate durante un blackout: i conteggi vengono dall'outbox, quindi sono esatti).
- OFFLINE: impacchetta l'ultima finestra chiusa in `AGG` da 26 byte (C4-B) e la passa al canale di backup (LoRa o BLE).
           Gli aggregati LoRa sono "provvisori": il backend li sostituisce con i dati esatti dopo il backfill.
Lo stato (ultima finestra pubblicata per canale) è salvato nell'outbox: sopravvive ai riavvii.
"""
import logging
import time

from payload import TYPE_AGG, pack_agg, summarize

log = logging.getLogger("agg")
MAX_CATCHUP_WINDOWS = 96          # al massimo 1 giorno di finestre a 15 min per ciclo


class Aggregator:
    def __init__(self, outbox, uplink, backup, period_s, node_id, state=None):
        self.ob, self.up, self.backup = outbox, uplink, backup
        self.P = period_s
        self.node = node_id
        self.state = state             # NodeState di main.py: ultimi env/batt/mode (None nei test)
        now_w = self._window_start(time.time())
        self.next_mqtt = float(self.ob.get_meta("agg_next_mqtt", now_w))
        self.next_lora = float(self.ob.get_meta("agg_next_lora", now_w))

    def _window_start(self, t):
        return (int(t) // self.P) * self.P

    def _agg(self, w, now):
        """Aggregato C4 della finestra che inizia in w. I dati ambientali solo se la finestra è appena chiusa."""
        env = self.state.env if self.state is not None and w + 2 * self.P > now else None
        return summarize(self.ob.events_between(w, w + self.P), w, w + self.P, self.node, env, self.ob.backlog())

    def tick(self, now=None):
        now = time.time() if now is None else now
        last_closed = self._window_start(now) - self.P          # inizio dell'ultima finestra chiusa

        if self.up.online():
            self.backup.idle()                                 # MQTT sano: backup a riposo
            # recupera tutte le finestre non ancora pubblicate via MQTT
            start = max(self.next_mqtt, last_closed - (MAX_CATCHUP_WINDOWS - 1) * self.P)
            w = start
            while w <= last_closed:
                ok = self.up.publish("agg", self._agg(w, now))
                if not ok:
                    break
                w += self.P
            if w != self.next_mqtt:
                self.next_mqtt = w
                self.ob.set_meta("agg_next_mqtt", w)
            # online: la finestra corrente non serve anche via LoRa
            if self.next_lora <= last_closed:
                self.next_lora = last_closed + self.P
                self.ob.set_meta("agg_next_lora", self.next_lora)
        elif self.next_lora <= last_closed:
            # offline: solo l'ultima finestra chiusa (l'airtime LoRa è prezioso)
            st = self.state
            pkt = pack_agg(self._agg(last_closed, now), self.ob.backlog(),
                           batt=st.batt if st else None, degraded=st is not None and st.mode() != "normal")
            if self.backup.send(pkt, TYPE_AGG):
                log.info("aggregato %d passato al canale di backup (%d byte)", last_closed, len(pkt))
                self.next_lora = last_closed + self.P
                self.ob.set_meta("agg_next_lora", self.next_lora)
