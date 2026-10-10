from arduino.app_utils import App, Bridge, Logger
from arduino.app_bricks.web_ui import WebUI

from vision import VisionService   # MDGB: camera -> smartcrossing (ai/) -> sketch + live view (vision.py)

logger = Logger("security-system")

# WebUI: the technician's panel in assets/ (sensor check, traffic light, live view with the boxes, log).
# Every notification of the sketch also tells vision.health that the sensor is alive (health.py).
ui = WebUI()
vision = VisionService(ui)

# --- Callbacks Bridge ---

def alarm_status(msg: str):
    logger.info(f"🚨 ALLARME  -> {msg}")
    vision.note("alarm", msg)

def led_status(status_msg: str):
    logger.info(f"LED        -> {status_msg}")
    # The vehicle lantern as the sketch really lit it (setPhase): shown as a traffic light on the page.
    for word, lamp in (("VERDE", "green"), ("GIALLO", "yellow"), ("ROSSO", "red")):
        if f"LED {word}" in status_msg:
            vision.health.seen("lamp", lamp)
    if "VISIONE" in status_msg or "FAIL-SAFE" in status_msg:
        vision.note("link", status_msg)

def sensor_movement(x: float, y: float, z: float):
    logger.info(f"ACCEL      -> X={x:.2f}g Y={y:.2f}g Z={z:.2f}g")
    vision.health.seen("accel", [round(x, 2), round(y, 2), round(z, 2)])

def sensor_env(temp: float, hum: float):
    logger.info(f"AHT20      -> Temp={temp:.1f}°C, Umidità={hum:.1f}%")
    vision.health.seen("env", [round(temp, 1), round(hum, 1)])

def sensor_air(eco2: float, tvoc: float):
    logger.info(f"SGP30      -> eCO2={int(eco2)} ppm, TVOC={int(tvoc)} ppb")
    vision.health.seen("air", [int(eco2), int(tvoc)])

def sensor_light(light_val: float):
    logger.info(f"LUCE       -> Valore={int(light_val)} / 1023")
    vision.health.seen("light", int(light_val))

def rfid_data(tag_id: str):
    logger.info(f"RFID       -> Tag Rilevato: {tag_id}")
    vision.note("rfid", f"badge letto: ...{tag_id[-4:]}")   # never the full code on the page
    vision.health.seen("rfid", f"badge ...{tag_id[-4:]}")

def rfid_status(status: str):
    logger.info(f"SICUREZZA  -> {status}")
    vision.note("rfid", status)

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
