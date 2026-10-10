"""Sorgenti di eventi (righe C3/C5 di docs/CONTRACTS.md v1).

Ogni sorgente chiama on_event(dict) per gli eventi da mettere nello Store & Forward e on_info(dict) per le righe
che aggiornano solo lo stato del nodo (`status` di C3, `env` di C5). Il resto del sistema non sa se gli eventi
vengono dai file scritti da ai/ o dal simulatore.
"""
import json
import logging
import os
import random
import threading
import time

from payload import INFO_TYPES

log = logging.getLogger("source")

# distribuzione indicativa degli utenti di un attraversamento urbano
SIM_MIX = [("pedestrian", 0.55), ("car", 0.25), ("cyclist", 0.10), ("motorcyclist", 0.04), ("bus", 0.02),
           ("truck", 0.02), ("animal", 0.02)]


class SimulatedSource:
    """Arrivi di Poisson con tasso medio rate_hz: serve per sviluppare e testare senza camera."""

    def __init__(self, rate_hz=0.5, seed=None, status_s=5.0):
        self.rate = rate_hz
        self.status_s = status_s
        self.rng = random.Random(seed)
        self._stop = threading.Event()
        self._track = 0

    def make_event(self, ts=None):
        """Una riga C3 plausibile (crossing, a volte near_miss o yield)."""
        r, ts = self.rng, time.time() if ts is None else ts
        self._track += 1
        if r.random() < 0.01:
            return {"v": 1, "ts": ts, "type": "near_miss", "a": self._track, "b": self._track + 1,
                    "ttc_s": round(r.uniform(0.3, 1.0), 2), "pet_s": None}
        cls = r.choices(*zip(*SIM_MIX))[0]
        if cls == "car" and r.random() < 0.3:
            return {"v": 1, "ts": ts, "type": "yield", "track_id": self._track, "yielded": r.random() < 0.5}
        ev = {"v": 1, "ts": ts, "type": "crossing", "track_id": self._track, "cls": cls,
              "dir": r.choice(["in", "out"]), "line": "ped" if cls in ("pedestrian", "cyclist") else "veh"}
        if cls == "pedestrian":
            ev["attrs"] = {"child": r.random() < 0.05, "slow": r.random() < 0.10,
                           "aid": r.choice(["wheelchair", "stroller"]) if r.random() < 0.04 else None}
        if cls == "animal":
            ev["coco"] = "dog"
        return ev

    def start(self, on_event, on_info=None):
        def run():
            t_status = 0.0
            while not self._stop.is_set():
                self._stop.wait(self.rng.expovariate(self.rate))
                if self._stop.is_set():
                    break
                on_event(self.make_event())
                now = time.time()
                if on_info and now - t_status >= self.status_s:
                    on_info({"v": 1, "ts": now, "type": "status", "state": "PRESENCE", "fps": 9.6})
                    t_status = now

        threading.Thread(target=run, name="sim-source", daemon=True).start()
        log.info("sorgente simulata avviata (%.2f eventi/s)", self.rate)

    def stop(self):
        self._stop.set()


class C3FileSource:
    """Legge i file JSONL di $MDGB_C3_DIR: c3-*.jsonl (scritti da ai/) e mcu-*.jsonl (righe C5, scritte da
    comms/actuators.py). Gli eventi vanno nell'outbox INSIEME al cursore (file, offset), nella stessa transazione:
    se il processo cade non si perde e non si duplica nessuna riga. Una riga senza "\\n" si legge solo quando è
    completa; in un file ormai ruotato (ne esiste uno più nuovo) un resto incompleto si salta."""

    SERIES = ("c3", "mcu")
    MAX_READ = 256 * 1024             # per file e per giro: il backlog si recupera a pezzi

    def __init__(self, directory, outbox, poll_s=0.2):
        self.dir, self.ob, self.poll_s = directory, outbox, poll_s
        self._stop = threading.Event()

    def start(self, on_event=None, on_info=None):
        """on_event non serve: gli eventi vanno direttamente nell'outbox (insieme al cursore)."""
        def run():
            while not self._stop.is_set():
                try:
                    self.poll(on_info)
                except Exception:
                    log.exception("lettura dei file C3 fallita")
                self._stop.wait(self.poll_s)

        threading.Thread(target=run, name="c3-source", daemon=True).start()
        log.info("sorgente C3 su file: %s", self.dir)

    def stop(self):
        self._stop.set()

    def poll(self, on_info=None) -> int:
        return sum(self._poll_series(s, on_info) for s in self.SERIES)

    def _poll_series(self, series, on_info):
        key = f"cursor_{series}"
        cur_file, cur_off = json.loads(self.ob.get_meta(key, '["", 0]'))
        try:
            files = sorted(f for f in os.listdir(self.dir) if f.startswith(series + "-") and f.endswith(".jsonl"))
        except FileNotFoundError:
            return 0
        stored = 0
        for i, name in enumerate(files):
            if name < cur_file:
                continue
            off = cur_off if name == cur_file else 0
            with open(os.path.join(self.dir, name), "rb") as f:
                f.seek(off)
                data = f.read(self.MAX_READ)
            end = data.rfind(b"\n") + 1
            if end == 0:
                if i + 1 < len(files):
                    continue                  # resto incompleto di un file ruotato (scrittore caduto)
                break
            events, infos = [], []
            for raw in data[:end].splitlines():
                try:
                    obj = json.loads(raw)
                except ValueError:
                    log.warning("%s: riga non valida ignorata: %r", name, raw[:80])
                    continue
                if isinstance(obj, dict):
                    (infos if obj.get("type") in INFO_TYPES else events).append(obj)
            self.ob.put_many(events, meta={key: json.dumps([name, off + end])})
            stored += len(events)
            for obj in infos:
                if on_info:
                    on_info(obj)
            if len(data) == self.MAX_READ:
                break                         # c'è altro: al prossimo giro
        return stored


def make_source(kind, rate_hz, c3_dir=None, outbox=None):
    return C3FileSource(c3_dir, outbox) if kind == "c3" else SimulatedSource(rate_hz)
