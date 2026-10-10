"""Sorgente degli eventi del nodo: i file JSONL scritti sulla scheda da ai/ (C3) e da comms/actuators.py (C5),
docs/CONTRACTS.md v1. Le righe `status` (C3) ed `env`/`thermal` (C5) aggiornano solo lo stato del nodo (on_info);
tutte le altre sono eventi e vanno nello Store & Forward.
Per provare la rete senza la visione: comms/tools/c3_sim.py scrive righe C3 negli stessi file.
"""
import json
import logging
import os
import threading

from payload import INFO_TYPES

log = logging.getLogger("source")


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
        """Gli eventi vanno direttamente nell'outbox (insieme al cursore); on_event(dict) li riceve dopo,
        solo per aggiornare lo stato del nodo (es. C5 `failsafe` -> mode)."""
        def run():
            while not self._stop.is_set():
                try:
                    self.poll(on_info, on_event)
                except Exception:
                    log.exception("lettura dei file C3 fallita")
                self._stop.wait(self.poll_s)

        threading.Thread(target=run, name="c3-source", daemon=True).start()
        log.info("sorgente C3 su file: %s", self.dir)

    def stop(self):
        self._stop.set()

    def poll(self, on_info=None, on_event=None) -> int:
        return sum(self._poll_series(s, on_info, on_event) for s in self.SERIES)

    def _poll_series(self, series, on_info, on_event=None):
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
            for obj in events:
                if on_event:
                    on_event(obj)
            if len(data) == self.MAX_READ:
                break                         # c'è altro: al prossimo giro
        return stored
