from arduino.app_utils import App, Bridge, Logger
from arduino.app_bricks.web_ui import WebUI

from vision import VisionService   # MDGB: camera -> smartcrossing (ai/) -> sketch + live view (vision.py)

logger = Logger("security-system")

# --- Callbacks Bridge ---

def alarm_status(msg: str):
    logger.info(f"🚨 ALLARME  -> {msg}")

def led_status(status_msg: str):
    logger.info(f"LED        -> {status_msg}")

def sensor_movement(x: float, y: float, z: float):
    logger.info(f"ACCEL      -> X={x:.2f}g Y={y:.2f}g Z={z:.2f}g")

def sensor_env(temp: float, hum: float):
    logger.info(f"AHT20      -> Temp={temp:.1f}°C, Umidità={hum:.1f}%")

def sensor_air(eco2: float, tvoc: float):
    logger.info(f"SGP30      -> eCO2={int(eco2)} ppm, TVOC={int(tvoc)} ppb")

def sensor_light(light_val: float):
    logger.info(f"LUCE       -> Valore={int(light_val)} / 1023")

def rfid_data(tag_id: str):
    logger.info(f"RFID       -> Tag Rilevato: {tag_id}")

def rfid_status(status: str):
    logger.info(f"SICUREZZA  -> {status}")

# WebUI: the page in assets/ shows what the camera sees, with a box on every person and vehicle recognised.
ui = WebUI()
vision = VisionService(ui)

def mcu_event(line: str):
    # C5 lines of the sketch (tamper, badge, fail-safe): the vision reads them (smartcrossing/mcu.py)
    vision.on_mcu_line(line)

# Registrazione delle funzioni Bridge
Bridge.provide("alarm_status", alarm_status)
Bridge.provide("led_status", led_status)
Bridge.provide("sensor_movement", sensor_movement)
Bridge.provide("sensor_env", sensor_env)
Bridge.provide("sensor_air", sensor_air)
Bridge.provide("sensor_light", sensor_light)
Bridge.provide("rfid_data", rfid_data)
Bridge.provide("rfid_status", rfid_status)
Bridge.provide("mcu_event", mcu_event)

# The vision runs in its own thread: if it stops, the heartbeat stops and the sketch goes back to the normal
# cycle by itself within 500 ms (fail-safe).
vision.start()

App.run()
