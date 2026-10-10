"""Configurazione del nodo. Ogni valore si può sovrascrivere con una variabile d'ambiente."""
import os


def _env(name, default, cast=str):
    v = os.environ.get(name)
    if v is None:
        return default
    if cast is bool:
        return v.strip().lower() in ("1", "true", "yes", "on")
    return cast(v)


NODE_ID = _env("NODE_ID", "xw-001")
TOPIC_PREFIX = _env("TOPIC_PREFIX", "torino/crosswalk")

# --- MQTT (canale primario: TCP/IP via Wi-Fi/Ethernet/4G) ---
# Sviluppo locale: Mosquitto sul laptop, TCP 1883 senza TLS.
# AWS IoT Core:    MQTT_HOST=<xxxx-ats.iot.<region>.amazonaws.com>, MQTT_PORT=8883 (o 443 con ALPN),
#                  MQTT_TLS=1 e i tre file del certificato X.509 del "Thing" (NODE_ID = nome del Thing).
MQTT_HOST = _env("MQTT_HOST", "localhost")
MQTT_PORT = _env("MQTT_PORT", 1883, int)          # 1883 = TCP in chiaro, 8883 = TCP+TLS, 443 = TLS+ALPN
MQTT_TLS = _env("MQTT_TLS", False, bool)
MQTT_CA = _env("MQTT_CA", "")                     # es. certs/AmazonRootCA1.pem
MQTT_CERT = _env("MQTT_CERT", "")                 # es. certs/xw-001.cert.pem
MQTT_KEY = _env("MQTT_KEY", "")                   # es. certs/xw-001.private.key
MQTT_USER = _env("MQTT_USER", "")                 # non usato con AWS IoT (autenticazione via certificato)
MQTT_PASS = _env("MQTT_PASS", "")
MQTT_SESSION_EXPIRY_S = _env("MQTT_SESSION_EXPIRY_S", 3600, int)   # AWS IoT: default 1 h, max configurabile 7 gg
MQTT_BATCH = _env("MQTT_BATCH", 50, int)          # eventi per messaggio di backfill
MQTT_ACK_TIMEOUT_S = _env("MQTT_ACK_TIMEOUT_S", 30, int)

# --- Store & Forward ---
DB_PATH = _env("DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "outbox.db"))
RETENTION_MAX_ROWS = _env("RETENTION_MAX_ROWS", 2_000_000, int)  # oltre: si cancellano i più vecchi GIA' inviati

# --- Aggregati / canale di backup LoRa ---
AGG_PERIOD_S = _env("AGG_PERIOD_S", 900, int)     # 15 min in produzione, 60 s per la demo
HEARTBEAT_S = _env("HEARTBEAT_S", 30, int)
ALERT_SECONDS = _env("ALERT_SECONDS", 8, int)     # estensione "verde pedonale" per utenti lenti

# --- Canale di backup (attivo solo quando MQTT non è sano) ---
BACKUP_LINK = _env("BACKUP_LINK", "ble")          # "ble" (prototipo, radio integrata) | "lora" (Wio-E5 via MCU) | "none"
BLE_SUDO = _env("BLE_SUDO", False, bool)          # True se il processo non gira come root

# --- Sorgente eventi ---
EVENT_SOURCE = _env("EVENT_SOURCE", "sim")        # "sim" ora, "vision" quando la pipeline video è pronta
SIM_RATE_HZ = _env("SIM_RATE_HZ", 0.5, float)     # eventi/secondo medi del simulatore
