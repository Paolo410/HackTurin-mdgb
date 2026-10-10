"""Sorgenti di eventi di attraversamento.

Ogni sorgente chiama on_crossing(label, direction, confidence) quando qualcuno attraversa
la linea virtuale. Il resto del sistema non sa se l'evento viene dalla telecamera o dal simulatore.
"""
import logging
import random
import threading
import time

log = logging.getLogger("source")

# distribuzione indicativa degli utenti di un attraversamento urbano
SIM_MIX = [("person", 0.78), ("bicycle", 0.12), ("stroller", 0.05), ("wheelchair", 0.03), ("other", 0.02)]


class SimulatedSource:
    """Arrivi di Poisson con tasso medio rate_hz: serve per sviluppare e testare senza camera."""

    def __init__(self, rate_hz=0.5, seed=None):
        self.rate = rate_hz
        self.rng = random.Random(seed)
        self._stop = threading.Event()

    def start(self, on_crossing):
        labels, weights = zip(*SIM_MIX)

        def run():
            while not self._stop.is_set():
                self._stop.wait(self.rng.expovariate(self.rate))
                if self._stop.is_set():
                    break
                label = self.rng.choices(labels, weights)[0]
                on_crossing(label, self.rng.randint(0, 1), self.rng.uniform(0.55, 0.98))

        threading.Thread(target=run, name="sim-source", daemon=True).start()
        log.info("sorgente simulata avviata (%.2f eventi/s)", self.rate)

    def stop(self):
        self._stop.set()


class VisionSource:
    """Segnaposto per la pipeline camera -> YOLO -> ByteTrack -> LineZone (prossimo passo)."""

    def start(self, on_crossing):
        raise NotImplementedError("pipeline video non ancora implementata: usa EVENT_SOURCE=sim")

    def stop(self):
        pass


def make_source(kind, rate_hz):
    return VisionSource() if kind == "vision" else SimulatedSource(rate_hz)
