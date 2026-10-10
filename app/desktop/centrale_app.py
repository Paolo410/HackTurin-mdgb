"""MDGB Centrale: l'app per il PC della centrale (doppio clic e funziona).

Avvia la centrale (MQTT + Bluetooth + dashboard, vedi app/central.py) e mostra la dashboard in una finestra.
Chiudendo la finestra si ferma tutto. Impostazioni, certificati e database stanno in una cartella dell'utente:
  macOS   ~/Library/Application Support/MDGB Centrale/      Windows  %APPDATA%\\MDGB Centrale\\
  Linux   ~/.config/mdgb-centrale/                           (oppure la cartella in MDGB_HOME)
con dentro:
  config.env    broker (locale o AWS IoT Core), Bluetooth, porta della dashboard   <- creato al primo avvio
  certs/        certificati AWS del Thing della centrale (mdgb-ingest)
  nodes.json    camere sulla mappa (copiato al primo avvio; si modifica anche ad app aperta)
  central.db    database della centrale             centrale.log   log dell'app
Se il broker è "localhost" e non risponde, l'app avvia il Mosquitto che ha dentro (o quello installato nel sistema).

Da sorgente:   python app/desktop/centrale_app.py        App:   app/desktop/build_mac.sh -> "MDGB Centrale.app"
"""
import logging
import os
import re
import shutil
import socket
import subprocess
import sys
import time

APP_NAME = "MDGB Centrale"
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

# --- Modalità AWS IoT Core: metti un # davanti alle 3 righe sopra e toglilo da queste.
#     I tre file del certificato vanno nella cartella certs/ accanto a questo file (comms/aws/setup_thing.sh).
# MQTT_HOST=xxxxxxxxxxxx-ats.iot.eu-central-1.amazonaws.com
# MQTT_PORT=8883
# MQTT_TLS=1
# MQTT_CA=certs/AmazonRootCA1.pem
# MQTT_CERT=certs/mdgb-ingest.cert.pem
# MQTT_KEY=certs/mdgb-ingest.private.key
# INGEST_CLIENT_ID=mdgb-ingest

# --- Bluetooth: canale di backup dei nodi. BLE=0 per spegnerlo. BLE_NODE = nodo a cui appartengono i beacon ---
BLE=1
BLE_NODE=nodo01

# --- Dashboard: 127.0.0.1 = solo questo PC; 0.0.0.0 = anche da telefono/tablet sulla stessa rete ---
WEB_HOST=127.0.0.1
WEB_PORT=8080

# --- Mappa: chiave di Google Maps (Maps JavaScript API). Vuota = mappa senza chiave; senza Internet = schematica ---
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


def find_mosquitto():
    """Prima la copia dentro l'app (build_mac.sh la include), poi quella installata nel sistema."""
    for p in (os.path.join(RESOURCES, "mosquitto", "mosquitto"), shutil.which("mosquitto"),
              "/opt/homebrew/sbin/mosquitto", "/usr/local/sbin/mosquitto",
              "/usr/sbin/mosquitto", r"C:\Program Files\mosquitto\mosquitto.exe"):
        if p and os.path.exists(p):
            return p
    return None


def ensure_local_broker(home, port):
    """Modalità locale: se nessun broker risponde sulla porta, avvia Mosquitto (aperto alla rete locale, per i nodi)."""
    if port_open(port):
        log.info("broker locale già attivo sulla porta %d", port)
        return None
    exe = find_mosquitto()
    if exe is None:
        log.error("nessun broker sulla porta %d e Mosquitto non è installato (brew install mosquitto)", port)
        return None
    conf = os.path.join(home, "mosquitto.conf")
    with open(conf, "w") as f:
        f.write(f"listener {port} 0.0.0.0\nallow_anonymous true\npersistence true\n"
                f"persistence_location {os.path.join(home, 'mosquitto-data')}/\nmax_queued_messages 100000\n")
    os.makedirs(os.path.join(home, "mosquitto-data"), exist_ok=True)
    proc = subprocess.Popen([exe, "-c", conf], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
        webview.create_window(APP_NAME, url, width=1320, height=900, min_size=(900, 600))
        webview.start()
        return
    import webbrowser                                   # ripiego: dashboard nel browser, l'app resta aperta
    webbrowser.open(url)
    log.warning("pywebview non installato: dashboard aperta nel browser; Ctrl-C per chiudere")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def main():
    home = home_dir()
    cfg_path = prepare_home(home)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(os.path.join(home, "centrale.log")), logging.StreamHandler()])
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
    try:
        show_window(c.url)
    finally:
        log.info("chiusura: fermo la centrale")
        c.stop()
        if broker is not None:
            broker.terminate()
            broker.wait(5)


if __name__ == "__main__":
    main()
