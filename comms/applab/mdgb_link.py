"""MDGB: inoltra alla rete i sensori e gli allarmi dello sketch di Salvatore. Va nella cartella python/ dell'app di
App Lab, accanto a main.py, che lo usa con `import mdgb_link` (docs/CONTRACTS.md v1, righe C5).

Le notifiche dello sketch (Bridge.notify) arrivano a main.py; qui diventano righe C5 scritte in
/app/data/c3/applab-*.jsonl, cioè ~/ArduinoApps/<app>/data/c3/ sulla scheda. La rete (comms/node/main.py) gira come
servizio sul Linux della scheda, fuori da App Lab, perché il container di App Lab non può usare il Bluetooth, e
legge quella cartella (MDGB_C3_DIR in comms/.env). Solo libreria standard: in App Lab non c'è niente da installare.

    sensor_env/light/air (ogni 300 ms)  -> una riga "env" ogni 10 s con gli ultimi valori
    alarm_status (tentato furto)        -> "tamper" code 1 (urto), al massimo una ogni 10 s
    rfid_status "ACCESSO CONSENTITO"    -> "tamper" code 3 (badge del tecnico: informazione, non allarme)
    led_status "FAIL-SAFE: ..."         -> "failsafe" (semaforo nel ciclo normale: la visione non risponde). Passa da qui
                                           perché il fail-safe scatta proprio quando la visione, che riceve gli
                                           mcu_event dello sketch, è ferma
    il resto (LED, accelerazioni, codice del badge) resta nel log di App Lab: non serve alla centrale
"""
import functools
import json
import os
import threading
import time

C3_DIR = os.environ.get("MDGB_C3_DIR") or ("/app/data/c3" if os.path.isdir("/app") else os.path.join("data", "c3"))
SERIES = "applab"          # file applab-*.jsonl: una serie tutta sua, letta dal nodo insieme a c3-* e mcu-*
ENV_EVERY_S = 10.0         # C5 env: ogni 10 s
ALARM_HOLD_S = 10.0        # lo sketch ripete l'allarme a ogni campione (300 ms): uno ogni 10 s basta
ROTATE_S = 3600.0          # un file nuovo ogni ora, come comms/jsonl.py

_lock = threading.Lock()
_f, _opened_at = None, 0.0
_env, _t_env = {}, 0.0
_last = {}                 # tipo di allarme -> ultimo invio


def _write(obj):
    """Una riga JSON completa, flush + fsync: il nodo la legge una volta sola, anche dopo un riavvio."""
    global _f, _opened_at
    obj = dict({"v": 1, "src": "mcu", "ts": round(time.time(), 3)}, **obj)
    line = json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n"
    with _lock:
        now = time.time()
        if _f is None or now - _opened_at >= ROTATE_S:
            if _f is not None:
                _f.close()
            os.makedirs(C3_DIR, exist_ok=True)
            name = time.strftime(f"{SERIES}-%Y%m%d-%H%M%S.jsonl", time.gmtime(now))
            _f, _opened_at = open(os.path.join(C3_DIR, name), "a", encoding="utf-8"), now
        _f.write(line)
        _f.flush()
        os.fsync(_f.fileno())


def _safe(fn):
    """La rete non deve mai far cadere main.py: un errore qui si stampa e basta."""
    @functools.wraps(fn)
    def wrapper(*args):
        try:
            fn(*args)
        except Exception as e:
            print(f"mdgb_link: {fn.__name__} fallita: {e}", flush=True)
    return wrapper


def _env_update(**values):
    global _t_env
    _env.update(values)
    now = time.time()
    if now - _t_env >= ENV_EVERY_S:
        _t_env = now
        _write(dict(type="env", **_env))


@_safe
def env(temp_c, humidity):
    """sensor_env dell'AHT20."""
    _env_update(t_c=round(float(temp_c), 1), rh=round(float(humidity), 1))


@_safe
def light(raw):
    """sensor_light: valore grezzo 0-1023 del sensore di luce (non sono lux)."""
    _env_update(light=int(raw))


@_safe
def air(eco2, tvoc):
    """sensor_air dell'SGP30."""
    _env_update(eco2_ppm=int(eco2), tvoc_ppb=int(tvoc))


def _alarm(kind, **fields):
    now = time.time()
    if now - _last.get(kind, 0.0) >= ALARM_HOLD_S:
        _last[kind] = now
        _write(fields)


@_safe
def theft_alarm(msg=""):
    """alarm_status: accelerazione anomala -> manomissione, urto (code 1)."""
    _alarm("shock", type="tamper", code=1)


@_safe
def led_status(msg):
    """led_status: solo il fail-safe dello sketch va alla centrale (C5 failsafe, reason hb_timeout)."""
    if "FAIL-SAFE" in str(msg).upper():
        _alarm("failsafe", type="failsafe", reason="hb_timeout")


@_safe
def rfid_status(msg):
    """rfid_status: solo l'accesso consentito va alla centrale (badge del tecnico, code 3)."""
    if "CONSENTITO" in str(msg).upper():
        _alarm("badge", type="tamper", code=3)
