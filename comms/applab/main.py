from arduino.app_utils import App, Bridge, Logger
from arduino.app_bricks.web_ui import WebUI
from arduino.app_peripherals.camera import Camera

import mdgb_link   # MDGB: sensori e allarmi verso la rete (mdgb_link.py, nella stessa cartella)

logger = Logger("security-system")

# --- Callbacks Bridge ---

def alarm_status(msg: str):
    logger.info(f"🚨 ALLARME  -> {msg}")
    mdgb_link.theft_alarm(msg)

def led_status(status_msg: str):
    logger.info(f"LED        -> {status_msg}")
    mdgb_link.led_status(status_msg)

def sensor_movement(x: float, y: float, z: float):
    logger.info(f"ACCEL      -> X={x:.2f}g Y={y:.2f}g Z={z:.2f}g")

def sensor_env(temp: float, hum: float):
    logger.info(f"AHT20      -> Temp={temp:.1f}°C, Umidità={hum:.1f}%")
    mdgb_link.env(temp, hum)

def sensor_air(eco2: float, tvoc: float):
    logger.info(f"SGP30      -> eCO2={int(eco2)} ppm, TVOC={int(tvoc)} ppb")
    mdgb_link.air(eco2, tvoc)

def sensor_light(light_val: float):
    logger.info(f"LUCE       -> Valore={int(light_val)} / 1023")
    mdgb_link.light(light_val)

def rfid_data(tag_id: str):
    logger.info(f"RFID       -> Tag Rilevato: {tag_id}")

def rfid_status(status: str):
    logger.info(f"SICUREZZA  -> {status}")
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

# Inizializzazione Camera e WebUI
camera = Camera(resolution=(640, 480), fps=15)
ui = WebUI()
camera.start()

ui.expose_camera("/camera", camera)

App.run()
