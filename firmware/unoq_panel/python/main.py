from arduino.app_utils import App, Bridge, Logger
from arduino.app_bricks.web_ui import WebUI

from panel import Panel   # MDGB: pannello del tecnico (panel.py, health.py, assets/)
import mdgb_link          # MDGB: sensori, urto, badge e fail-safe verso la centrale (comms/applab/mdgb_link.py)

logger = Logger("security-system")
panel = Panel()

# --- Callbacks Bridge ---

def alarm_status(msg: str):
    logger.info(f"🚨 ALLARME  -> {msg}")
    panel.note("alarm", msg)
    mdgb_link.theft_alarm(msg)

def led_status(status_msg: str):
    logger.info(f"LED        -> {status_msg}")
    panel.led_status(status_msg)
    mdgb_link.led_status(status_msg)

def sensor_movement(x: float, y: float, z: float):
    logger.info(f"ACCEL      -> X={x:.2f}g Y={y:.2f}g Z={z:.2f}g")
    panel.seen("accel", [round(x, 2), round(y, 2), round(z, 2)])

def sensor_env(temp: float, hum: float):
    logger.info(f"AHT20      -> Temp={temp:.1f}°C, Umidità={hum:.1f}%")
    panel.seen("env", [round(temp, 1), round(hum, 1)])
    mdgb_link.env(temp, hum)

def sensor_air(eco2: float, tvoc: float):
    logger.info(f"SGP30      -> eCO2={int(eco2)} ppm, TVOC={int(tvoc)} ppb")
    panel.seen("air", [int(eco2), int(tvoc)])
    mdgb_link.air(eco2, tvoc)

def sensor_light(light_val: float):
    logger.info(f"LUCE       -> Valore={int(light_val)} / 1023")
    panel.seen("light", int(light_val))
    mdgb_link.light(light_val)

def rfid_data(tag_id: str):
    logger.info(f"RFID       -> Tag Rilevato: {tag_id}")
    panel.badge(tag_id)

def rfid_status(status: str):
    logger.info(f"SICUREZZA  -> {status}")
    panel.note("rfid", status)
    mdgb_link.rfid_status(status)

# Registrazione delle funzioni Bridge
Bridge.provide("alarm_status", alarm_status)
Bridge.provide("led_status", led_status)
Bridge.provide("sensor_movement", sensor_movement)
Bridge.provide("sensor_env", sensor_env)
Bridge.provide("sensor_air", sensor_air)
Bridge.provide("sensor_light", sensor_light)
Bridge.provide("rfid_data", rfid_data)
Bridge.provide("rfid_status", rfid_status)

# WebUI: solo la pagina di assets/ (rimanda alla pagina del tecnico della visione).
# La camera non si apre piu' qui: la usa la visione (ai/), che gira come servizio accanto a questa app.
# Una camera sola non puo' essere letta da due programmi insieme.
ui = WebUI()
panel.start(ui)   # pagina del tecnico: controllo sensori, semaforo, traffico, registro

App.run()
