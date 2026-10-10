"""Configurazione del nodo. Ogni valore si può sovrascrivere con una variabile d'ambiente
o, più comodo, nel file comms/.env (copiato da comms/.env.example, ignorato da git)."""
import os
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_dotenv(path):
    """Legge KEY=VALUE da un file .env (ignorato da git) senza sovrascrivere le variabili già impostate."""
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), re.split(r"\s+#", v, maxsplit=1)[0].strip())
    except FileNotFoundError:
        pass


_load_dotenv(os.path.join(REPO_ROOT, "comms", ".env"))


def _path(v):
    """Percorsi relativi (es. certs/nodo01.cert.pem) = relativi alla root del repo, da qualunque cartella si lanci."""
    return v if not v or os.path.isabs(v) else os.path.join(REPO_ROOT, v)


def _env(name, default, cast=str):
    v = os.environ.get(name)
    if v is None:
        return default
    if cast is bool:
        return v.strip().lower() in ("1", "true", "yes", "on")
    return cast(v)


NODE_ID = _env("NODE_ID", "nodo01")                # nome del nodo = client ID MQTT (docs/CONTRACTS.md C4)
TOPIC_PREFIX = _env("TOPIC_PREFIX", "mdgb")

# --- MQTT (canale primario: Wi-Fi) ---
# Demo:            MQTT_HOST = IP del PC della centrale (broker Mosquitto dentro l'app), MQTT_PORT=1883, MQTT_TLS=0.
# Cloud (futuro):  MQTT_HOST = broker in cloud, MQTT_PORT=8883, MQTT_TLS=1 e i file del certificato del nodo.
MQTT_HOST = _env("MQTT_HOST", "localhost")
MQTT_PORT = _env("MQTT_PORT", 1883, int)          # 1883 = TCP in chiaro, 8883 = TCP+TLS, 443 = TLS+ALPN
MQTT_TLS = _env("MQTT_TLS", False, bool)
MQTT_CA = _path(_env("MQTT_CA", ""))                     # es. certs/ca.pem
MQTT_CERT = _path(_env("MQTT_CERT", ""))                 # es. certs/nodo01.cert.pem
MQTT_KEY = _path(_env("MQTT_KEY", ""))                   # es. certs/nodo01.private.key
MQTT_USER = _env("MQTT_USER", "")                 # facoltativo, se il broker usa utente e password
MQTT_PASS = _env("MQTT_PASS", "")
MQTT_SESSION_EXPIRY_S = _env("MQTT_SESSION_EXPIRY_S", 3600, int)   # il broker tiene la sessione per 1 h
MQTT_BATCH = _env("MQTT_BATCH", 50, int)          # eventi per messaggio di backfill
MQTT_ACK_TIMEOUT_S = _env("MQTT_ACK_TIMEOUT_S", 30, int)
MQTT_ACK_WINDOW_S = _env("MQTT_ACK_WINDOW_S", 30, int)   # "online" = PUBACK positivo negli ultimi 30 s
MQTT_NACK_BACKOFF_MAX_S = _env("MQTT_NACK_BACKOFF_MAX_S", 60, int)  # attesa massima dopo un PUBACK negativo
HB_PERIOD_S = _env("HB_PERIOD_S", 10, int)          # heartbeat MQTT `hb` (retained): dà conferme anche senza eventi

# --- Store & Forward ---
DB_PATH = _path(_env("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "outbox.db")))
RETENTION_MAX_ROWS = _env("RETENTION_MAX_ROWS", 2_000_000, int)  # oltre: si cancellano i più vecchi GIA' inviati

# --- Aggregati ---
AGG_PERIOD_S = _env("AGG_PERIOD_S", 900, int)     # 15 min in produzione, 60 s per la demo

# --- Canale di backup (attivo solo quando MQTT non è sano) ---
BACKUP_LINK = _env("BACKUP_LINK", "ble")          # "ble" (prototipo, radio integrata) | "lora" (Wio-E5 via MCU) | "none"
BLE_SUDO = _env("BLE_SUDO", False, bool)          # True se il processo non gira come root
BACKUP_ON_AFTER_S = _env("BACKUP_ON_AFTER_S", 30, float)    # acceso dopo 30 s senza PUBACK positivi
BACKUP_OFF_AFTER_S = _env("BACKUP_OFF_AFTER_S", 60, float)  # spento dopo 60 s di MQTT stabile
BACKUP_HB_S = _env("BACKUP_HB_S", 300, float)               # HB sul backup: 5 min (nella demo anche 30 s)

# --- Eventi: i file JSONL scritti sulla scheda da ai/ (C3) e da comms/actuators.py (C5) ---
C3_DIR = _path(_env("MDGB_C3_DIR", os.path.join(REPO_ROOT, "logs", "c3")))
