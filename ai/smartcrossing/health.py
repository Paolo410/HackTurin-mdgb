"""Check of every part of the node for the technician's page: is each part sending plausible data?

Every part reports with Health.seen(key, value); Health.evaluate() turns age and value into one status per part:

    ok        sends plausible data
    warn      sends data, but something looks wrong (lens covered, light always 0, slow vision...)
    fault     nothing within its timeout, or impossible values
    waiting   nothing yet, still within the time the part needs to start
    untested  only shows up on demand (badge, shock): the technician tests it

Where the data comes from (app.py):
- camera, vision, link to the sketch, event file: measured by the vision loop itself;
- sensors of the board: the "env" lines that mdgb_link.py (App Lab app of the sketch) writes every 10 s;
- badge reader and accelerometer: the tamper lines of the same app (code 3 badge, code 1 shock).
Limit: mdgb_link.py repeats the last value of every sensor in its env lines, so from here a single sensor that
stops is not seen; what is seen is the sketch and its app going silent, and impossible values.

Same idea and same words as the panel of the App Lab app (firmware/unoq_mcu/python/health.py), with the parts
the vision service can see. Pure Python: tested on the PC.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable

OK, WARN, FAULT, WAITING, UNTESTED = "ok", "warn", "fault", "waiting", "untested"
PROBLEMS = (FAULT, WARN)
WORDS = {OK: "funziona", WARN: "da controllare", FAULT: "non funziona", WAITING: "in attesa", UNTESTED: "da provare"}

STARTUP_GRACE_S = 15.0       # camera and model start within this time
BOARD_GRACE_S = 40.0         # the env lines of the board come every 10 s and are read every 0.5 s
BOARD_TIMEOUT_S = 35.0       # three env lines missed: the App Lab app or the sketch stopped
VISION_MIN_FPS = 5.0         # below this the rule reacts too late (spec: >= 8 FPS)
AHT20_ZERO_C = -49.9         # raw reading 0 -> -50 C: the sensor did not answer (Adafruit AHTX0 formula)
LIGHT_SAMPLES = 6            # one minute of env lines: a light value that never moves is stuck
LIGHT_SATURATED = 1020

Judge = Callable[[object, deque], tuple[str, str, str]]   # (value, history) -> (status, detail, shown)


@dataclass
class Part:
    key: str
    name: str
    where: str                  # where it is connected or where its data comes from
    timeout_s: float | None     # None = data only when something happens (badge, shock)
    hint: str                   # what to do when it does not work
    judge: Judge
    grace_s: float = STARTUP_GRACE_S
    stale: str = "nessun dato da {age:.0f} s"
    never: tuple[str, str] = (FAULT, "nessun dato dall'avvio della visione")
    last_t: float | None = None
    value: object = None
    history: deque = field(default_factory=lambda: deque(maxlen=LIGHT_SAMPLES))
    status: str = WAITING
    detail: str = ""


def _camera(v: dict, _):
    shown = f"{v['w']}×{v['h']}" + (f", luminosità {v['lum']:.0f} su 255" if v.get("lum") is not None else "")
    if v.get("fault") == "lens_covered":
        return WARN, "immagine senza dettagli: lente coperta, sporca o sfocata", shown
    if v.get("fault") == "glare":
        return WARN, "immagine abbagliata (sole o fari in camera)", shown
    return OK, "immagini regolari", shown


def _vision(v: dict, _):
    shown = f"{v['fps']:.1f} FPS" + (f", rilevamento in {v['detect_ms']:.0f} ms" if v.get("detect_ms") else "")
    if v["fps"] and v["fps"] < VISION_MIN_FPS:
        return WARN, f"lenta: {v['fps']:.1f} FPS (ne servono almeno {VISION_MIN_FPS:.0f})", shown
    return OK, "riconosce persone, veicoli e animali", shown


def _link(v: dict, _):
    if v.get("sim"):
        return OK, "semaforo simulato: nessuno sketch collegato (--actuator sim)", "simulato"
    if v["failsafe"]:
        return FAULT, "lo sketch non riceve gli heartbeat: è in fail-safe e fa il ciclo normale", "fail-safe"
    return OK, "lo sketch riceve i comandi della visione", "collegato"


def _board(v: dict, _):
    return OK, "l'app di App Lab manda i dati dei sensori", "dati ogni 10 s"


def _env(v, _):
    t, rh = v
    shown = f"{t:.1f} °C, umidità {rh:.0f}%"
    if t <= AHT20_ZERO_C:
        return FAULT, "letture a zero: il sensore non risponde", shown
    if not (-40 <= t <= 85 and 0 <= rh <= 100):
        return WARN, "valori fuori dal campo del sensore", shown
    return OK, "valori plausibili", shown


def _air(v, _):
    eco2, tvoc = v
    shown = f"CO₂ {eco2} ppm, VOC {tvoc} ppb"
    if eco2 == 400 and tvoc == 0:
        return OK, "valore di base: normale appena acceso o in aria pulita", shown
    return OK, "valori plausibili", shown


def _light(v, history: deque):
    shown = f"{v} su 1023"
    full = len(history) == history.maxlen
    if full and all(h == 0 for h in history):
        return WARN, "legge sempre 0: coperto o scollegato?", shown
    if full and all(h >= LIGHT_SATURATED for h in history):
        return WARN, "sempre al massimo: sensore saturo o in corto?", shown
    return OK, "valori plausibili", shown


def _shock(v: float, _):
    return OK, "l'antifurto ha segnalato un urto", "urto rilevato"


def _badge(v: float, _):
    return OK, "ha letto il badge del tecnico", "badge letto"


def _storage(v: dict, _):
    if not v["enabled"]:
        return WARN, "salvataggio spento (logger.enabled o --no-c3): niente eventi per la centrale", "spento"
    if v.get("error"):
        return FAULT, f"errore di scrittura: {v['error']}", f"{v['written']} righe"
    return OK, "gli eventi vengono salvati per la centrale", f"{v['written']} righe salvate"


_BOARD_HINT = ("Controlla che l'app mdgb sia avviata in App Lab (arduino-app-cli app list) e che scriva in "
               "~/ArduinoApps/mdgb/data/c3, la stessa cartella della visione (push_to_arduino.sh --applab mdgb).")


def service_parts() -> list[Part]:
    """The parts the vision service can see."""
    return [
        Part("camera", "Camera", "camera della scheda, aperta dalla visione", 2.0,
             "Controlla il cavo flat della camera e che nessun altro programma la stia usando; se resta ferma "
             "serve un riavvio della scheda (ai/DECISIONS.md, punto 39).", _camera,
             stale="nessuna immagine da {age:.0f} s"),
        Part("vision", "Riconoscimento", "YOLOX-nano e tracking sulla CPU", 3.0,
             "Se è lenta: chiudi la vista dal vivo e le altre app della scheda. Se è ferma guarda il log del "
             "servizio (journalctl -u mdgb-ai).", _vision,
             stale="nessun fotogramma elaborato da {age:.0f} s"),
        Part("link", "Collegamento con lo sketch", "Bridge della UNO Q (arduino-router)", 3.0,
             "Controlla che l'app mdgb sia avviata in App Lab: lo sketch deve avere mdgb_line. Intanto il "
             "semaforo fa il ciclo normale.", _link),
        Part("board", "App di App Lab e sketch", "righe dei sensori scritte da mdgb_link.py", BOARD_TIMEOUT_S,
             _BOARD_HINT, _board, grace_s=BOARD_GRACE_S,
             stale="nessun dato dalla scheda da {age:.0f} s: app di App Lab o sketch fermi",
             never=(FAULT, "nessun dato dall'app di App Lab dall'avvio della visione")),
        Part("env", "Temperatura e umidità", "AHT20, porta I2C dello shield", BOARD_TIMEOUT_S,
             "Controlla il cavo Grove dell'AHT20 sulla porta I2C dello shield (selettore su 3,3 V).", _env,
             grace_s=BOARD_GRACE_S, never=(WARN, "nessun valore dell'AHT20 nelle righe della scheda")),
        Part("air", "Qualità dell'aria", "SGP30, porta I2C dello shield", BOARD_TIMEOUT_S,
             "Controlla il cavo Grove dell'SGP30 sulla porta I2C dello shield.", _air,
             grace_s=BOARD_GRACE_S, never=(WARN, "nessun valore dell'SGP30 nelle righe della scheda")),
        Part("light", "Sensore di luce", "pin A0 dello shield", BOARD_TIMEOUT_S,
             "Controlla il cavo Grove sul pin A0 e che il sensore non sia coperto.", _light,
             grace_s=BOARD_GRACE_S, never=(WARN, "nessun valore del sensore di luce nelle righe della scheda")),
        Part("shock", "Antifurto", "Modulino Movement (accelerometro), porta Qwiic", None,
             "Se scuotendo il supporto non compare l'urto, controlla il cavo Qwiic del Modulino Movement.", _shock,
             never=(UNTESTED, "si prova scuotendo piano il supporto: deve comparire un urto (il cicalino tace "
                              "finché sei dentro)")),
        Part("badge", "Lettore badge", "lettore RFID dello sketch", None,
             "Se il badge non viene letto controlla cavo e alimentazione del lettore.", _badge,
             never=(UNTESTED, "si prova passando il badge")),
        Part("storage", "Salvataggio eventi", "file C3 per la centrale", 5.0,
             "Controlla lo spazio libero (df -h) e i permessi della cartella degli eventi.", _storage,
             stale="la visione è ferma da {age:.0f} s: nessun evento salvato"),
    ]


class Health:
    def __init__(self, parts: list[Part] | None = None, clock: Callable[[], float] = time.monotonic,
                 on_change: Callable[[str, str], None] | None = None):
        """on_change(level, text): a part changed status (level "info" or "warning")."""
        self.parts = {p.key: p for p in (parts if parts is not None else service_parts())}
        self._clock = clock
        self._t0 = clock()
        self._on_change = on_change
        self._lock = threading.Lock()   # data arrives from the vision loop and from the threads of the MCU lines
        self._startup_reported = False

    def seen(self, key: str, value=None) -> None:
        """A part sent data now."""
        with self._lock:
            part = self.parts[key]
            part.last_t = self._clock()
            part.value = value
            part.history.append(value)

    def on_mcu_line(self, line: dict) -> None:
        """A C5 line of the microcontroller (Bridge or files of the App Lab app)."""
        if not isinstance(line, dict):
            return
        kind = line.get("type")
        if kind == "env":
            self.seen("board", line)
            if "t_c" in line and "rh" in line:
                self.seen("env", (float(line["t_c"]), float(line["rh"])))
            if "eco2_ppm" in line:
                self.seen("air", (int(line["eco2_ppm"]), int(line.get("tvoc_ppb", 0))))
            if "light" in line:
                self.seen("light", int(line["light"]))
        elif kind == "tamper":
            self.seen("badge" if line.get("code") == 3 else "shock", self._clock())

    def evaluate(self) -> dict:
        """Status of every part now and the summary. Reports the changes through on_change."""
        now = self._clock()
        checks = []
        with self._lock:
            for part in self.parts.values():
                status, detail, shown = self._judge(part, now)
                if status != part.status:
                    self._changed(part, status, detail)
                part.status, part.detail = status, detail
                checks.append({
                    "key": part.key, "name": part.name, "where": part.where, "status": status, "detail": detail,
                    "shown": shown, "age_s": None if part.last_t is None else round(now - part.last_t, 1),
                    "hint": part.hint if status in PROBLEMS else "",
                })
        summary = self._summary(checks)
        if not self._startup_reported and now - self._t0 >= BOARD_GRACE_S:
            self._startup_reported = True
            bad = [c["name"] for c in checks if c["status"] in PROBLEMS]
            self._report("warning" if bad else "info",
                         f"controllo iniziale: {summary['ok']} su {len(checks)} a posto"
                         + (f"; da guardare: {', '.join(bad)}" if bad else ""))
        return {"checks": checks, "summary": summary}

    def _judge(self, part: Part, now: float) -> tuple[str, str, str]:
        if part.last_t is None:
            if part.never[0] != UNTESTED and now - self._t0 < part.grace_s:
                return WAITING, "in attesa del primo dato", ""
            return part.never[0], part.never[1], ""
        age = now - part.last_t
        if part.timeout_s is not None and age > part.timeout_s:
            _, _, shown = self._value(part)
            return FAULT, part.stale.format(age=age), f"ultimo: {shown}" if shown else ""
        return self._value(part)

    @staticmethod
    def _value(part: Part) -> tuple[str, str, str]:
        try:
            return part.judge(part.value, part.history)
        except (TypeError, ValueError, KeyError, IndexError):
            return WARN, "dato non leggibile", str(part.value)

    def _changed(self, part: Part, status: str, detail: str) -> None:
        if part.status == WAITING and status in (OK, UNTESTED):
            return   # normal start: not worth a line
        if status in PROBLEMS:
            self._report("warning", f"{part.name} {WORDS[status]}: {detail}")
        elif part.status in PROBLEMS:
            self._report("info", f"{part.name} di nuovo a posto")
        elif part.status == UNTESTED and status == OK:
            self._report("info", f"{part.name} provato: funziona")

    def _report(self, level: str, text: str) -> None:
        if self._on_change is not None:
            self._on_change(level, text)

    @staticmethod
    def _summary(checks: list[dict]) -> dict:
        count = {s: sum(c["status"] == s for c in checks) for s in (OK, WARN, FAULT, WAITING, UNTESTED)}
        overall = FAULT if count[FAULT] else WARN if count[WARN] else WAITING if count[WAITING] else OK
        return {"overall": overall, **count, "total": len(checks)}
