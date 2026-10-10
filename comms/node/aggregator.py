"""Aggregatore a finestre fisse (es. 15 min) con doppia uscita.

- ONLINE : pubblica su MQTT `agg` in JSON tutte le finestre chiuse e non ancora pubblicate
           (anche quelle maturate durante un blackout: i conteggi vengono dall'outbox, quindi sono esatti).
- OFFLINE: impacchetta l'ultima finestra chiusa in 28 byte e la passa al canale di backup (LoRa o BLE).
           Gli aggregati LoRa sono "provvisori": il backend li sostituisce con i dati esatti dopo il backfill.
Lo stato (ultima finestra pubblicata per canale) è salvato nell'outbox: sopravvive ai riavvii.
"""
import logging
import shutil
import time

from payload import CATEGORIES, pack_aggregate

log = logging.getLogger("agg")
MAX_CATCHUP_WINDOWS = 96          # al massimo 1 giorno di finestre a 15 min per ciclo


class Aggregator:
    def __init__(self, outbox, uplink, backup, period_s, disk_path):
        self.ob, self.up, self.backup = outbox, uplink, backup
        self.P = period_s
        self.disk_path = disk_path
        now_w = self._window_start(time.time())
        self.next_mqtt = float(self.ob.get_meta("agg_next_mqtt", now_w))
        self.next_lora = float(self.ob.get_meta("agg_next_lora", now_w))

    def _window_start(self, t):
        return (int(t) // self.P) * self.P

    def _disk_free_pct(self):
        try:
            du = shutil.disk_usage(self.disk_path)
            return 100 * du.free / du.total
        except OSError:
            return 0

    def tick(self, now=None):
        now = time.time() if now is None else now
        last_closed = self._window_start(now) - self.P          # inizio dell'ultima finestra chiusa

        if self.up.online():
            self.backup.idle()                                 # MQTT sano: backup a riposo
            # recupera tutte le finestre non ancora pubblicate via MQTT
            start = max(self.next_mqtt, last_closed - (MAX_CATCHUP_WINDOWS - 1) * self.P)
            w = start
            while w <= last_closed:
                counts = self.ob.counts(w, w + self.P)
                ok = self.up.publish("agg", {
                    "window_start": int(w), "period_s": self.P, "source": "mqtt",
                    "dir0": dict(zip(CATEGORIES, counts[0])),
                    "dir1": dict(zip(CATEGORIES, counts[1])),
                    "backlog": self.ob.backlog()})
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
            counts = self.ob.counts(last_closed, last_closed + self.P)
            pkt = pack_aggregate(last_closed, counts, self.ob.backlog(), self._disk_free_pct(), online=False)
            if self.backup.send(pkt):
                log.info("aggregato %d passato al canale di backup (%d byte)", last_closed, len(pkt))
                self.next_lora = last_closed + self.P
                self.ob.set_meta("agg_next_lora", self.next_lora)
