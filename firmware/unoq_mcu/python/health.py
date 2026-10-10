"""Health of every part of the node, for the technician: is each sensor sending plausible values?

Every part reports with Health.seen(key, value): the sketch notifications from main.py, the camera, the AI and
the link from vision.py. Health.evaluate() turns age and value into one status per part:

    ok        sends plausible values
    warn      sends values, but something looks wrong (lens covered, light always 0, slow AI...)
    fault     no data within its timeout, or impossible values
    waiting   nothing yet, still within STARTUP_GRACE_S of the start
    untested  works only on demand (badge reader): needs a test by the technician

Pure Python, no Arduino import: it can be tried on the PC.
"""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

OK, WARN, FAULT, WAITING, UNTESTED = "ok", "warn", "fault", "waiting", "untested"
PROBLEMS = (FAULT, WARN)

STARTUP_GRACE_S = 15.0       # time for the sketch, the camera and the model to start before "no data" is a fault
SKETCH_SENSOR_S = 5.0        # the sketch sends every sensor every 500 ms (sensorInterval)
AI_MIN_FPS = 5.0             # below this the vision is too slow for the rule (spec: >= 8 FPS)
ACCEL_MIN_G, ACCEL_MAX_G = 0.65, 1.15   # same thresholds as the anti-theft alarm of the sketch
AHT20_ZERO_C = -49.9         # raw reading 0 -> -50 C: the sensor did not answer (Adafruit AHTX0 formula)
LIGHT_SAMPLES = 10           # light readings kept to tell a stuck sensor from a dark scene
LIGHT_SATURATED = 1020


@dataclass
class Part:
    key: str
    name: str
    where: str                  # where it is connected, for the technician
    timeout_s: float | None     # None = sends only on demand (no timeout)
    hint: str                   # what to do when it does not work
    stale: str = "nessun dato da {age:.0f} s"
    untested: str = ""
    last_t: float | None = None
    value: object = None
    history: deque = field(default_factory=lambda: deque(maxlen=LIGHT_SAMPLES))
    status: str = WAITING
    detail: str = ""


def _parts() -> list[Part]:
    return [
        Part("camera", "Camera", "camera della scheda (CSI o USB)", 2.0,
             "Controlla il cavo flat della camera e che nessun altro programma la stia usando "
             "(run_vision.sh, servizio mdgb-ai). Verifiche in firmware/README.md, sezione Camera.",
             stale="nessuna immagine da {age:.0f} s"),
        Part("ai", "Riconoscimento (AI)", "YOLOX-nano + tracking sulla CPU", 3.0,
             "Guarda i log dell'app in App Lab: la visione si riavvia da sola dopo un errore. "
             "Se è solo lenta, chiudi le altre app sulla scheda.",
             stale="nessun fotogramma elaborato da {age:.0f} s"),
        Part("link", "Collegamento con lo sketch", "Bridge Linux ↔ microcontrollore", 3.0,
             "Riavvia l'app da App Lab. Se resta così, ricarica lo sketch. Intanto il semaforo fa il ciclo normale.",
             stale="la visione non manda heartbeat da {age:.0f} s: lo sketch è in fail-safe"),
        Part("lamp", "Ciclo del semaforo", "LED pin 11-13 comandati dallo sketch", 60.0,
             "Lo sketch non segnala cambi di fase: riavvia l'app; se persiste ricarica lo sketch.",
             stale="nessun cambio di fase da {age:.0f} s"),
        Part("accel", "Accelerometro", "Modulino Movement, porta Qwiic", SKETCH_SENSOR_S,
             "Controlla il cavo Qwiic del Modulino Movement e che sia fissato bene al supporto della camera."),
        Part("env", "Temperatura e umidità", "AHT20, porta I2C dello shield", SKETCH_SENSOR_S,
             "Controlla il cavo Grove dell'AHT20 sulla porta I2C dello shield (selettore su 3,3 V)."),
        Part("air", "Qualità dell'aria", "SGP30, porta I2C dello shield", SKETCH_SENSOR_S,
             "Controlla il cavo Grove dell'SGP30 sulla porta I2C dello shield."),
        Part("light", "Sensore di luce", "pin A0 dello shield", SKETCH_SENSOR_S,
             "Controlla il cavo Grove sul pin A0 e che il sensore non sia coperto."),
        Part("rfid", "Lettore badge", "lettore RFID su Serial1", None,
             "Passa il badge: se non compare nulla controlla il cavo e l'alimentazione del lettore.",
             untested="passa il badge sul lettore per provarlo"),
        Part("storage", "Salvataggio eventi", "file C3 nella cartella data/ dell'app", 5.0,
             "Controlla lo spazio libero sulla scheda (df -h) e i permessi della cartella data/ dell'app.",
             stale="la visione è ferma da {age:.0f} s: nessun evento salvato"),
    ]


# ---------- per-part judgement: value -> (status, detail, display) ----------

def _camera(v: dict):
    shown = f"{v['w']}×{v['h']}" + (f" · luminosità {v['lum']:.0f}/255" if v.get("lum") is not None else "")
    if v.get("fault") == "lens_covered":
        return WARN, "immagine senza dettagli: lente coperta, sporca o sfocata", shown
    if v.get("fault") == "glare":
        return WARN, "immagine abbagliata (sole o fari in camera)", shown
    return OK, "immagini regolari", shown


def _ai(v: dict):
    shown = f"{v['fps']:.1f} FPS" + (f" · rilevamento {v['detect_ms']:.0f} ms" if v.get("detect_ms") else "")
    if v["fps"] and v["fps"] < AI_MIN_FPS:
        return WARN, f"lenta: {v['fps']:.1f} FPS (servono almeno {AI_MIN_FPS:.0f})", shown
    return OK, "riconosce persone, veicoli e animali", shown


def _link(v: dict):
    shown = f"comandi {v['c1']} · heartbeat {v['c2']}"
    if v["failsafe"]:
        return FAULT, "lo sketch non accetta gli heartbeat: è in fail-safe (ciclo normale)", shown
    if v["rejected"]:
        return WARN, f"{v['rejected']} righe rifiutate dallo sketch", shown
    return OK, "lo sketch riceve i comandi della visione", shown


_LAMP_NAMES = {"green": "verde", "yellow": "giallo", "red": "rosso"}


def _lamp(v: str):
    return OK, "lo sketch cambia fase regolarmente", f"fase veicoli: {_LAMP_NAMES.get(v, v)}"


def _accel(v):
    x, y, z = v
    g = math.sqrt(x * x + y * y + z * z)
    shown = f"{g:.2f} g"
    if g == 0.0:
        return FAULT, "legge sempre 0: il sensore non risponde", shown
    if not ACCEL_MIN_G <= g <= ACCEL_MAX_G:
        return WARN, f"scossa o urto in corso ({g:.2f} g)", shown
    return OK, "fermo, nessuna scossa", shown


def _env(v):
    t, rh = v
    shown = f"{t:.1f} °C · {rh:.0f} %"
    if t <= AHT20_ZERO_C:
        return FAULT, "letture a zero: il sensore non risponde", shown
    if not (-40 <= t <= 85 and 0 <= rh <= 100):
        return WARN, "valori fuori dal campo del sensore", shown
    return OK, "valori plausibili", shown


def _air(v):
    eco2, tvoc = v
    shown = f"eCO₂ {eco2} ppm · TVOC {tvoc} ppb"
    if eco2 == 400 and tvoc == 0:
        return OK, "valore di base: normale nei primi 15 s o in aria pulita", shown
    return OK, "valori plausibili", shown


def _light(v, history: deque):
    shown = f"{v} / 1023"
    full = len(history) == history.maxlen
    if full and all(h == 0 for h in history):
        return WARN, "legge sempre 0: coperto o scollegato?", shown
    if full and all(h >= LIGHT_SATURATED for h in history):
        return WARN, "sempre al massimo: sensore saturo o in corto?", shown
    return OK, "valori plausibili", shown


def _rfid(v: str):
    return OK, "ha letto almeno un badge", f"ultimo: {v}"


def _storage(v: dict):
    if not v["enabled"]:
        return WARN, "salvataggio disattivato in config.yaml (logger.enabled)", "spento"
    if v.get("error"):
        return FAULT, f"errore di scrittura: {v['error']}", f"{v['written']} righe"
    return OK, "gli eventi vengono salvati", f"{v['written']} righe salvate"


_JUDGES = {"camera": _camera, "ai": _ai, "link": _link, "lamp": _lamp, "accel": _accel, "env": _env,
           "air": _air, "rfid": _rfid, "storage": _storage}

_STATUS_WORDS = {OK: "funziona", WARN: "da controllare", FAULT: "non funziona", WAITING: "in attesa",
                 UNTESTED: "da provare"}


class Health:
    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 on_change: Callable[[str, str], None] | None = None):
        """on_change(level, text): called when a part changes status (level: "info" or "warning")."""
        self.parts = {p.key: p for p in _parts()}
        self._clock = clock
        self._t0 = clock()
        self._on_change = on_change
        self._lock = threading.Lock()   # values arrive from the Bridge threads and from the vision thread
        self._startup_reported = False

    def seen(self, key: str, value=None) -> None:
        """A part sent a value now."""
        with self._lock:
            part = self.parts[key]
            part.last_t = self._clock()
            part.value = value
            part.history.append(value)

    def evaluate(self) -> dict:
        """Status of every part now, plus the overall summary. Reports the changes through on_change."""
        now = self._clock()
        checks = []
        with self._lock:
            for part in self.parts.values():
                status, detail, shown = self._judge(part, now)
                if status != part.status:
                    self._changed(part, status, detail)
                part.status, part.detail = status, detail
                checks.append({
                    "key": part.key, "name": part.name, "where": part.where, "status": status,
                    "detail": detail, "value": part.value if isinstance(part.value, (int, float, str, list)) else None,
                    "shown": shown, "age_s": None if part.last_t is None else round(now - part.last_t, 1),
                    "hint": part.hint if status in PROBLEMS else "",
                })
        summary = self._summary(checks)
        if not self._startup_reported and now - self._t0 >= STARTUP_GRACE_S:
            self._startup_reported = True
            bad = [c["name"] for c in checks if c["status"] in PROBLEMS]
            text = (f"controllo iniziale: {summary['ok']} su {len(checks)} funzionano"
                    + (f"; da guardare: {', '.join(bad)}" if bad else ""))
            self._report("warning" if bad else "info", text)
        return {"checks": checks, "summary": summary}

    def _judge(self, part: Part, now: float) -> tuple[str, str, str]:
        if part.last_t is None:
            if part.timeout_s is None:
                return UNTESTED, part.untested, "—"
            if now - self._t0 < STARTUP_GRACE_S:
                return WAITING, "in attesa del primo dato", "—"
            return FAULT, "nessun dato dall'avvio dell'app", "—"
        age = now - part.last_t
        if part.timeout_s is not None and age > part.timeout_s:
            _, _, shown = self._value(part)
            return FAULT, part.stale.format(age=age), f"ultimo: {shown}"
        return self._value(part)

    @staticmethod
    def _value(part: Part) -> tuple[str, str, str]:
        try:
            if part.key == "light":
                return _light(part.value, part.history)
            return _JUDGES[part.key](part.value)
        except (TypeError, ValueError, KeyError, IndexError):
            return WARN, "valore non leggibile", str(part.value)

    def _changed(self, part: Part, status: str, detail: str) -> None:
        if part.status == WAITING and status in (OK, UNTESTED):
            return   # normal start: not worth a line
        if status in PROBLEMS:
            self._report("warning", f"{part.name}: {_STATUS_WORDS[status]} — {detail}")
        elif part.status in PROBLEMS:
            self._report("info", f"{part.name}: di nuovo a posto")
        elif part.status == UNTESTED and status == OK:
            self._report("info", f"{part.name}: provato, funziona")

    def _report(self, level: str, text: str) -> None:
        if self._on_change is not None:
            self._on_change(level, text)

    @staticmethod
    def _summary(checks: list[dict]) -> dict:
        count = {s: sum(c["status"] == s for c in checks) for s in (OK, WARN, FAULT, WAITING, UNTESTED)}
        overall = FAULT if count[FAULT] else WARN if count[WARN] else WAITING if count[WAITING] else OK
        return {"overall": overall, **count, "total": len(checks)}
