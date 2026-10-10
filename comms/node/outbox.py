"""Store & Forward: coda persistente su eMMC (SQLite in modalità WAL).

Regola d'oro: un evento viene scritto qui PRIMA di qualsiasi tentativo di invio,
e viene marcato come inviato SOLO dopo l'ACK del broker (PUBACK MQTT QoS 1).
`seq` (AUTOINCREMENT) non viene mai riusato: il backend lo usa per deduplicare
e per rilevare buchi (= dati persi).
"""
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
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS events(
                seq  INTEGER PRIMARY KEY AUTOINCREMENT,
                ts   REAL    NOT NULL,
                cat  INTEGER NOT NULL,
                dir  INTEGER NOT NULL,
                conf REAL    NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0);
            CREATE INDEX IF NOT EXISTS ix_events_sent ON events(sent, seq);
            CREATE INDEX IF NOT EXISTS ix_events_ts   ON events(ts);
            CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        """)

    # ---------- eventi ----------
    def put(self, ts: float, cat: int, direction: int, conf: float) -> int:
        with self._lock:
            return self._db.execute(
                "INSERT INTO events(ts,cat,dir,conf) VALUES(?,?,?,?)",
                (ts, cat, direction, conf)).lastrowid

    def pending(self, limit: int):
        with self._lock:
            return self._db.execute(
                "SELECT seq,ts,cat,dir,conf FROM events WHERE sent=0 ORDER BY seq LIMIT ?",
                (limit,)).fetchall()

    def ack(self, seqs):
        with self._lock:
            self._db.execute("BEGIN")
            self._db.executemany("UPDATE events SET sent=1 WHERE seq=?", [(s,) for s in seqs])
            self._db.execute("COMMIT")

    def backlog(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM events WHERE sent=0").fetchone()[0]

    def counts(self, t0: float, t1: float):
        """Matrice 2x5 [direzione][categoria] degli eventi nella finestra [t0, t1)."""
        m = [[0] * 5 for _ in range(2)]
        with self._lock:
            rows = self._db.execute(
                "SELECT dir,cat,COUNT(*) FROM events WHERE ts>=? AND ts<? GROUP BY dir,cat",
                (t0, t1)).fetchall()
        for d, c, n in rows:
            if d in (0, 1) and 0 <= c < 5:
                m[d][c] = n
        return m

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
