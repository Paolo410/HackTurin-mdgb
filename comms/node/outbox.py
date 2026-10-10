"""Store & Forward: coda persistente su eMMC (SQLite in modalità WAL).

Regola d'oro: un evento viene scritto qui PRIMA di qualsiasi tentativo di invio,
e viene marcato come inviato SOLO dopo l'ACK del broker (PUBACK MQTT QoS 1).
`seq` (AUTOINCREMENT) non viene mai riusato: il backend lo usa per deduplicare
e per rilevare buchi (= dati persi).
Ogni evento è la riga C3/C5 così com'è (docs/CONTRACTS.md v1): `type` e `ts` sono copiati in colonna.
"""
import json
import os
import sqlite3
import threading


class Outbox:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA synchronous=FULL")      # durabilità anche in caso di power-loss
        cols = [r[1] for r in self._db.execute("PRAGMA table_info(events)")]
        if cols and "body" not in cols:
            raise RuntimeError(f"{path}: outbox del prototipo (formato vecchio): spostalo o cambia DB_PATH")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS events(
                seq  INTEGER PRIMARY KEY AUTOINCREMENT,
                ts   REAL    NOT NULL,
                type TEXT    NOT NULL,
                body TEXT    NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS ix_events_sent ON events(sent, seq);
            CREATE INDEX IF NOT EXISTS ix_events_ts   ON events(ts);
            CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        """)

    # ---------- eventi ----------
    def put(self, ev: dict) -> int:
        return self.put_many([ev])[0]

    def put_many(self, evs, meta=None):
        """Scrive gli eventi e (opzionale) aggiorna `meta` nella STESSA transazione: chi legge i file C3
        salva qui il proprio cursore, così dopo un crash non perde né duplica righe. Ritorna i seq."""
        rows = [(float(ev.get("ts") or 0), str(ev.get("type", "")), json.dumps(ev, separators=(",", ":")))
                for ev in evs]
        with self._lock:
            self._db.execute("BEGIN")
            try:
                seqs = [self._db.execute("INSERT INTO events(ts,type,body) VALUES(?,?,?)", r).lastrowid
                        for r in rows]
                for k, v in (meta or {}).items():
                    self._db.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, str(v)))
                self._db.execute("COMMIT")
            except Exception:
                self._db.execute("ROLLBACK")
                raise
        return seqs

    def pending(self, limit: int):
        """[(seq, body JSON)] non ancora confermati, dal più vecchio."""
        with self._lock:
            return self._db.execute(
                "SELECT seq,body FROM events WHERE sent=0 ORDER BY seq LIMIT ?",
                (limit,)).fetchall()

    def ack(self, seqs):
        with self._lock:
            self._db.execute("BEGIN")
            self._db.executemany("UPDATE events SET sent=1 WHERE seq=?", [(s,) for s in seqs])
            self._db.execute("COMMIT")

    def backlog(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM events WHERE sent=0").fetchone()[0]

    def events_between(self, t0: float, t1: float):
        """Eventi (dict) con ts nella finestra [t0, t1): servono agli aggregati esatti."""
        with self._lock:
            rows = self._db.execute("SELECT body FROM events WHERE ts>=? AND ts<?", (t0, t1)).fetchall()
        return [json.loads(b) for (b,) in rows]

    def prune(self, max_rows: int) -> int:
        """Retention: se la tabella supera max_rows cancella i più vecchi GIA' inviati.
        Gli eventi non inviati non vengono mai toccati."""
        with self._lock:
            total = self._db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            excess = total - max_rows
            if excess <= 0:
                return 0
            return self._db.execute(
                "DELETE FROM events WHERE seq IN (SELECT seq FROM events WHERE sent=1 ORDER BY seq LIMIT ?)",
                (excess,)).rowcount

    # ---------- stato persistente (es. ultima finestra aggregata) ----------
    def get_meta(self, k, default=None):
        with self._lock:
            r = self._db.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
        return r[0] if r else default

    def set_meta(self, k, v):
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, str(v)))
