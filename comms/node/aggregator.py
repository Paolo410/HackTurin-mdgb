"""Aggregatore a finestre fisse (es. 15 min) verso MQTT `agg` (docs/CONTRACTS.md v1, C4).

Quando MQTT è online pubblica tutte le finestre chiuse e non ancora pubblicate, anche quelle maturate durante
un blackout: i conteggi vengono dall'outbox, quindi sono esatti. Lo stato (prossima finestra da pubblicare) è
salvato nell'outbox e sopravvive ai riavvii.
Durante un blackout l'aggregato compatto (`AGG` da 26 byte) va sul canale di backup: lo manda failover.py, che usa
window_agg(); la centrale lo tiene come provvisorio finché non arriva quello esatto.
"""
import logging
import time

from payload import summarize

log = logging.getLogger("agg")
MAX_CATCHUP_WINDOWS = 96          # al massimo 1 giorno di finestre a 15 min per ciclo


class Aggregator:
    def __init__(self, outbox, uplink, period_s, node_id, state=None):
        self.ob, self.up = outbox, uplink
        self.P = period_s
        self.node = node_id
        self.state = state             # NodeState di main.py: ultimi env/batt/mode (None nei test)
        self.next_mqtt = float(self.ob.get_meta("agg_next_mqtt", self._window_start(time.time())))

    def _window_start(self, t):
        return (int(t) // self.P) * self.P

    def window_agg(self, w, now):
        """Aggregato C4 della finestra che inizia in w. I dati ambientali solo se la finestra è appena chiusa."""
        env = self.state.env if self.state is not None and w + 2 * self.P > now else None
        return summarize(self.ob.events_between(w, w + self.P), w, w + self.P, self.node, env, self.ob.backlog())

    def tick(self, now=None):
        now = time.time() if now is None else now
        if not self.up.online():
            return
        last_closed = self._window_start(now) - self.P          # inizio dell'ultima finestra chiusa
        # recupera tutte le finestre non ancora pubblicate via MQTT
        w = max(self.next_mqtt, last_closed - (MAX_CATCHUP_WINDOWS - 1) * self.P)
        while w <= last_closed:
            if not self.up.publish("agg", self.window_agg(w, now)):
                break
            w += self.P
        if w != self.next_mqtt:
            self.next_mqtt = w
            self.ob.set_meta("agg_next_mqtt", w)
