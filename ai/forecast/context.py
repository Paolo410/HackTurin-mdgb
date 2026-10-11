"""What is known about the surroundings of each crossing, cached on disk. Standard library only.

get() never waits for the network: it returns what is in the cache and, if something is missing or old, starts
a background refresh. A source that fails is retried after a few minutes and its last good answer stays in
use, so the control room keeps working without Internet (PROMPT_SMART_CROSSING.md §5.3: external services are
never indispensable).
"""
import json
import logging
import os
import threading
import time

from . import sources

log = logging.getLogger("forecast")

DAY_S = 86400
TTL_S = {"poi": 30 * DAY_S, "esa": 365 * DAY_S, "google": 30 * DAY_S, "weather": 1800, "traffic": 1800}
RETRY_S = 300


def default_fetchers(google_key=""):
    """{part: f(lat, lon) -> dict}. The Google parts exist only with a key."""
    f = {"poi": sources.osm_pois, "esa": sources.esa_worldcover, "weather": sources.open_meteo}
    if google_key:
        f["google"] = lambda lat, lon: sources.google_places(lat, lon, google_key)
        f["traffic"] = lambda lat, lon: sources.google_traffic(lat, lon, google_key)
    return f


class Context:
    def __init__(self, cache_file=None, fetchers=None, clock=time.time, background=True):
        self.cache_file = cache_file
        self.fetchers = default_fetchers() if fetchers is None else fetchers
        self.clock, self.background = clock, background
        self.lock = threading.Lock()
        self.busy = set()
        self.cache = {}                     # {"lat,lon": {part: {"at": epoch_s, "data": {...}}, "_failed": {part: epoch_s}}}
        if cache_file and os.path.exists(cache_file):
            try:
                with open(cache_file, encoding="utf-8") as f:
                    self.cache = json.load(f)
            except (OSError, ValueError):
                log.warning("cache del contesto illeggibile (%s): si riparte da vuota", cache_file)

    @staticmethod
    def key(lat, lon):
        return "%.5f,%.5f" % (lat, lon)

    def _due(self, entry, now):
        """Parts to ask again: never fetched or expired, unless the last attempt failed a moment ago."""
        failed = entry.get("_failed", {})
        return [p for p in self.fetchers
                if (p not in entry or now - entry[p]["at"] >= TTL_S[p])
                and (p not in failed or now - failed[p] >= RETRY_S)]

    def get(self, lat, lon):
        """-> {part: data with "at"}, plus "pending": True while a refresh is running or about to start."""
        if lat is None or lon is None:
            return {"pending": False}
        k, now = self.key(lat, lon), self.clock()
        with self.lock:
            entry = self.cache.get(k, {})
            out = {p: dict(v["data"], at=v["at"]) for p, v in entry.items() if p != "_failed"}
            start = bool(self._due(entry, now)) and k not in self.busy
            if start and self.background:
                self.busy.add(k)
            out["pending"] = k in self.busy
        if start and self.background:
            threading.Thread(target=self.refresh, args=(lat, lon), name="forecast-context", daemon=True).start()
        return out

    def refresh(self, lat, lon):
        """Asks every due source, one after the other. Called in the background by get(), directly by the tests."""
        k = self.key(lat, lon)
        try:
            with self.lock:
                due = self._due(self.cache.get(k, {}), self.clock())
            for part in due:
                try:
                    data, failed = self.fetchers[part](lat, lon), None
                except Exception as e:          # no network, quota, a source that changed: the model does without
                    data, failed = None, e
                    log.warning("contesto %s per %s non disponibile: %s", part, k, e)
                with self.lock:
                    entry = self.cache.setdefault(k, {})
                    if failed is None:
                        entry[part] = {"at": self.clock(), "data": data}
                        entry.get("_failed", {}).pop(part, None)
                    else:
                        entry.setdefault("_failed", {})[part] = self.clock()
            self._save()
        finally:
            with self.lock:
                self.busy.discard(k)

    def _save(self):
        if not self.cache_file:
            return
        with self.lock:
            text = json.dumps(self.cache)
        try:
            tmp = self.cache_file + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(text)
            os.replace(tmp, self.cache_file)
        except OSError as e:
            log.warning("cache del contesto non salvata: %s", e)
