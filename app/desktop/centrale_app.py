"""MDGB Centrale: l'app per il PC della centrale (doppio clic e funziona).

Avvia la centrale (MQTT + Bluetooth + dashboard, vedi app/central.py) e mostra la dashboard in una finestra.
Chiudendo la finestra si ferma tutto. Impostazioni, certificati e database stanno in una cartella dell'utente:
  macOS   ~/Library/Application Support/MDGB Centrale/      Windows  %APPDATA%\\MDGB Centrale\\
  Linux   ~/.config/mdgb-centrale/                           (oppure la cartella in MDGB_HOME)
con dentro:
  config.env    broker (locale o in cloud), Bluetooth, porta della dashboard   <- creato al primo avvio
  certs/        solo con un broker in cloud: certificati TLS della centrale
  nodes.json    camere sulla mappa (copiato al primo avvio; si modifica anche ad app aperta)
  central.db    database della centrale             centrale.log   log dell'app
Se il broker è "localhost" e non risponde, l'app avvia il Mosquitto che ha dentro (o quello installato nel sistema).

Da sorgente:   python app/desktop/centrale_app.py
App:           macOS  app/desktop/build_mac.sh -> "MDGB Centrale.app"
               Windows app/desktop/build_windows.ps1 (o la build automatica su GitHub) -> "MDGB Centrale.exe"
Autotest:      "MDGB Centrale" --selftest   avvia broker, centrale e dashboard senza finestra, li controlla ed esce
               (codice 0 = tutto ok); usato dagli script di build.
"""
import atexit
import json
import logging
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

APP_NAME = "MDGB Centrale"
WINDOWS = sys.platform.startswith("win")
HERE = os.path.dirname(os.path.abspath(__file__))
APP_DIR = os.path.dirname(HERE)                                   # app/ (da sorgente)
RESOURCES = getattr(sys, "_MEIPASS", APP_DIR)                     # dentro l'app impacchettata: file in bundle
sys.path.insert(0, APP_DIR)

CONFIG_TEMPLATE = """\
# Configurazione di MDGB Centrale. Dopo le modifiche chiudi e riapri l'app.

# --- Modalità locale (predefinita): broker Mosquitto su questo PC; i nodi usano l'IP di questo PC, porta 1883 ---
MQTT_HOST=localhost
MQTT_PORT=1883
MQTT_TLS=0

# --- Broker in cloud (produzione, in futuro): metti un # davanti alle 3 righe sopra e toglilo da queste.
#     I file del certificato vanno nella cartella certs/ accanto a questo file.
# MQTT_HOST=broker.esempio.it
# MQTT_PORT=8883
# MQTT_TLS=1
# MQTT_CA=certs/ca.pem
# MQTT_CERT=certs/centrale.cert.pem
# MQTT_KEY=certs/centrale.key

# --- Bluetooth: canale di backup dei nodi. BLE=0 per spegnerlo. BLE_NODE = nodo a cui appartengono i beacon ---
BLE=1
BLE_NODE=nodo01

# --- Dashboard: 127.0.0.1 = solo questo PC; 0.0.0.0 = anche da telefono/tablet sulla stessa rete ---
WEB_HOST=127.0.0.1
WEB_PORT=8080

# --- Mappa: chiave di Google Maps (Maps JavaScript API). Vuota = mappa senza chiave; senza Internet = schematica.
#     La stessa chiave, con "Places API (New)" e "Routes API" abilitate, aggiunge al flusso atteso orari e
#     recensioni dei luoghi e il traffico (facoltativo: senza, il modello usa OpenStreetMap, ESA e il meteo) ---
GOOGLE_MAPS_API_KEY=
"""

log = logging.getLogger("app")


def home_dir():
    if os.environ.get("MDGB_HOME"):
        return os.environ["MDGB_HOME"]
    if sys.platform == "darwin":
        return os.path.expanduser(f"~/Library/Application Support/{APP_NAME}")
    if sys.platform.startswith("win"):
        return os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP_NAME)
    return os.path.expanduser("~/.config/mdgb-centrale")


def read_config(path):
    """KEY=VALUE con commenti (#) anche in fondo alla riga."""
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = re.split(r"\s+#", v, maxsplit=1)[0].strip()
    return out


def prepare_home(home):
    """Primo avvio: crea la cartella con config.env, certs/ e nodes.json."""
    os.makedirs(os.path.join(home, "certs"), exist_ok=True)
    cfg = os.path.join(home, "config.env")
    if not os.path.exists(cfg):
        with open(cfg, "w", encoding="utf-8") as f:
            f.write(CONFIG_TEMPLATE)
    nodes = os.path.join(home, "nodes.json")
    if not os.path.exists(nodes):
        shutil.copy(os.path.join(RESOURCES, "nodes.json"), nodes)
    return cfg


def port_open(port, host="127.0.0.1"):
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def find_mosquitto():
    """Prima la copia dentro l'app (gli script di build la includono), poi quella installata nel sistema."""
    for p in (os.path.join(RESOURCES, "mosquitto", "mosquitto.exe" if WINDOWS else "mosquitto"), shutil.which("mosquitto"),
              "/opt/homebrew/sbin/mosquitto", "/usr/local/sbin/mosquitto",
              "/usr/sbin/mosquitto", r"C:\Program Files\mosquitto\mosquitto.exe"):
        if p and os.path.exists(p):
            return p
    return None


def _is_mosquitto(pid):
    try:
        if WINDOWS:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                                 creationflags=subprocess.CREATE_NO_WINDOW).stdout
        else:
            out = subprocess.run(["ps", "-p", str(pid), "-o", "comm="], capture_output=True, text=True).stdout
        return "mosquitto" in out.lower()
    except OSError:
        return False


def stop_stale_broker(home):
    """Se l'app era stata chiusa di colpo (Cmd-Q, uscita forzata, crash) il suo Mosquitto può essere rimasto acceso:
    lo si ferma, dopo aver controllato che quel processo sia davvero Mosquitto."""
    pidf = os.path.join(home, "mosquitto.pid")
    try:
        with open(pidf) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        return
    if _is_mosquitto(pid):
        try:
            os.kill(pid, signal.SIGTERM)
            log.info("fermato il broker rimasto acceso dall'avvio precedente (pid %d)", pid)
            time.sleep(0.5)
        except OSError:
            pass
    try:
        os.remove(pidf)
    except OSError:
        pass


def stop_broker(proc, home):
    if proc is not None and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(5)
        except subprocess.TimeoutExpired:
            proc.kill()
    try:
        os.remove(os.path.join(home, "mosquitto.pid"))
    except OSError:
        pass


def ensure_local_broker(home, port):
    """Modalità locale: se nessun broker risponde sulla porta, avvia Mosquitto (aperto alla rete locale, per i nodi)."""
    stop_stale_broker(home)
    if port_open(port):
        log.info("broker locale già attivo sulla porta %d", port)
        return None
    exe = find_mosquitto()
    if exe is None:
        log.error("nessun broker sulla porta %d e Mosquitto non c'è (né dentro l'app né installato)", port)
        return None
    conf = os.path.join(home, "mosquitto.conf")
    data = os.path.join(home, "mosquitto-data").replace("\\", "/")   # Mosquitto accetta "/" anche su Windows
    with open(conf, "w") as f:
        f.write(f"listener {port} 0.0.0.0\nallow_anonymous true\npersistence true\n"
                f"persistence_location {data}/\nmax_queued_messages 100000\n")
    os.makedirs(os.path.join(home, "mosquitto-data"), exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if WINDOWS else 0           # su Windows niente finestra nera
    proc = subprocess.Popen([exe, "-c", conf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=flags)
    with open(os.path.join(home, "mosquitto.pid"), "w") as f:
        f.write(str(proc.pid))
    atexit.register(stop_broker, proc, home)          # anche se l'uscita non passa dalla finestra
    for _ in range(30):
        if port_open(port):
            break
        time.sleep(0.1)
    log.info("Mosquitto avviato dall'app (%s, porta %d)", exe, port)
    return proc


def show_window(url):
    """Finestra dell'app con la dashboard; ritorna quando l'utente la chiude."""
    try:
        import webview
    except ImportError:
        webview = None
    if webview is not None:
        try:
            webview.create_window(APP_NAME, url, width=1320, height=900, min_size=(900, 600))
            webview.start()                             # Windows: WebView2 (Edge), già presente in Windows 10/11
            return
        except Exception:
            log.exception("finestra non disponibile: apro la dashboard nel browser")
    import webbrowser                                   # ripiego: dashboard nel browser, l'app resta aperta
    webbrowser.open(url)
    log.warning("pywebview non installato: dashboard aperta nel browser; Ctrl-C per chiudere")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def selftest(url):
    """Controlla broker, centrale e dashboard senza finestra. Ritorna True se tutto risponde."""
    get = lambda path: urllib.request.urlopen(url + path, timeout=5).read()
    for _ in range(60):                                 # fino a 15 s perché la centrale si colleghi al broker
        info = json.loads(get("/api/info"))
        if info["mqtt"]["connected"]:
            break
        time.sleep(0.25)
    state = json.loads(get("/api/state"))
    forecast = json.loads(get("/api/forecast/nodo01"))  # il modello del flusso atteso è dentro l'app e risponde
    ok = (info["mqtt"]["connected"] and bool(state["nodes"]) and b"Centrale MDGB" in get("/")
          and forecast.get("available") is True)
    log.info("SELFTEST %s: mqtt=%s camere=%d mosquitto=%s flusso atteso=%s", "OK" if ok else "FALLITO", info["mqtt"],
             len(state["nodes"]), find_mosquitto(), forecast.get("available"))
    return ok


def main():
    test = "--selftest" in sys.argv
    if test and not os.environ.get("MDGB_HOME"):
        os.environ["MDGB_HOME"] = tempfile.mkdtemp(prefix="mdgb-selftest-")
    home = home_dir()
    cfg_path = prepare_home(home)
    if test:                                            # porte libere e niente Bluetooth: gira anche su una macchina di build
        with open(cfg_path, "w", encoding="utf-8") as f:
            f.write(CONFIG_TEMPLATE.replace("MQTT_PORT=1883", f"MQTT_PORT={free_port()}")
                    .replace("BLE=1", "BLE=0").replace("WEB_PORT=8080", f"WEB_PORT={free_port()}"))
    handlers = [logging.FileHandler(os.path.join(home, "centrale.log"), encoding="utf-8")]
    if sys.stderr is not None:                          # l'exe di Windows senza console non ha stderr
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s", handlers=handlers)
    cfg = read_config(cfg_path)
    os.environ.update(cfg)                              # la configurazione dell'app vince sull'ambiente
    os.environ.update({"MDGB_HOME": home, "INGEST_DB": os.path.join(home, "central.db"),
                       "NODES_FILE": os.path.join(home, "nodes.json")})
    for k in ("MQTT_CA", "MQTT_CERT", "MQTT_KEY"):    # percorsi relativi = relativi alla cartella dell'app
        v = os.environ.get(k)
        if v and not os.path.isabs(v):
            os.environ[k] = os.path.join(home, v)
    log.info("%s: impostazioni in %s", APP_NAME, home)

    broker = None
    host, port = cfg.get("MQTT_HOST", "localhost"), int(cfg.get("MQTT_PORT", 1883))
    if host in ("localhost", "127.0.0.1") and cfg.get("MQTT_TLS", "0") in ("0", "false", ""):
        broker = ensure_local_broker(home, port)

    import central                                      # dopo aver impostato l'ambiente (ingest lo legge all'import)
    c = central.Central(node=cfg.get("BLE_NODE", "nodo01"), use_ble=cfg.get("BLE", "1") == "1",
                        host=cfg.get("WEB_HOST", "127.0.0.1"), port=int(cfg.get("WEB_PORT", 8080))).start()
    ok = True
    try:
        if test:
            ok = selftest(c.url)
        else:
            show_window(c.url)
    finally:
        log.info("chiusura: fermo la centrale")
        c.stop()
        stop_broker(broker, home)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
