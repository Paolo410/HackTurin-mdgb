"""Ponte verso l'MCU STM32U585 (Arduino Bridge / RPC MessagePack su UART interna).

Sull'UNO Q:   Python (Linux)  --Bridge.call-->  sketch MCU  --UART D0/D1-->  modulo LoRa
Sul laptop:   nessun Bridge disponibile -> SimulatedMcu registra le chiamate a log,
              così puoi sviluppare e testare tutto il resto senza la scheda.
"""
import logging

log = logging.getLogger("mcu")

try:
    from arduino.app_utils import Bridge      # disponibile solo dentro App Lab sull'UNO Q
    ON_UNO_Q = True
except ImportError:
    Bridge = None
    ON_UNO_Q = False


class McuLink:
    """Funzioni esposte dallo sketch con Bridge.provide(...) (docs/CONTRACTS.md v1, sezione Bridge).
    C1/C2 verso l'MCU passano da comms/actuators.py: qui serve solo la radio LoRa (produzione)."""

    def _call(self, name, *args):
        try:
            return Bridge.call(name, *args)
        except Exception as e:                  # l'MCU non deve mai far cadere la pipeline
            log.error("Bridge.call(%s) fallita: %s", name, e)
            return False

    def lora_send(self, payload: bytes, port: int = 1) -> bool:
        """Accoda un uplink LoRa (fPort = type C4-B). Ritorna subito: la trasmissione avviene nel loop() dell'MCU."""
        return bool(self._call("lora_send", int(port), payload.hex().upper()))

    def lora_joined(self) -> bool:
        return bool(self._call("lora_joined"))


class SimulatedMcu:
    """Stessa interfaccia di McuLink, per girare sul laptop."""

    def __init__(self):
        self.sent = []          # (fPort, payload) "trasmessi via LoRa" (utile nei test)

    def lora_send(self, payload: bytes, port: int = 1) -> bool:
        self.sent.append((port, payload))
        log.info("[SIM LoRa] uplink fPort %d, %d byte: %s", port, len(payload), payload.hex().upper())
        return True

    def lora_joined(self) -> bool:
        return True


def make_mcu():
    return McuLink() if ON_UNO_Q else SimulatedMcu()


# ======================================================================================
# Canale di backup intercambiabile: LoRa (via MCU) oppure BLE (radio integrata nella UNO Q)
#   config.BACKUP_LINK = "lora" | "ble" | "none"
#   Interfaccia comune:  send(payload, port=1) -> bool   |   idle()  (chiamata quando MQTT è sano)
# ======================================================================================
import shlex
import struct
import subprocess

BLE_COMPANY_ID = 0xFFFF            # ID riservato ai test dal Bluetooth SIG (in produzione: ID registrato)
BLE_FRAME_SIZE = 27                # 31 byte di advertising - 4 di header manufacturer data
PORT_AGGREGATE = 1                 # = TYPE_AGG di payload.py (C4-B)


def ble_frame(payload: bytes, port: int = PORT_AGGREGATE) -> bytes:
    """Messaggio C4-B -> frame BLE da 27 byte: type(1) | corpo (al massimo 26 byte), zeri in coda."""
    if len(payload) > BLE_FRAME_SIZE - 1:
        raise ValueError(f"corpo di {len(payload)} byte: al massimo {BLE_FRAME_SIZE - 1}")
    return (bytes([port]) + payload).ljust(BLE_FRAME_SIZE, b"\x00")


class McuLoraBackup:
    """Backup via LoRa: il payload va all'MCU con Bridge, l'MCU lo trasmette col Wio-E5 (fPort = type)."""

    kind = "lora"

    def __init__(self, mcu):
        self.mcu = mcu
        self.active = False

    def send(self, payload: bytes, port: int = PORT_AGGREGATE) -> bool:
        ok = self.mcu.lora_send(payload, port)
        self.active = self.active or ok
        return ok

    def idle(self):
        self.active = False


class BleBackup:
    """Backup via BLE advertising (beacon non connettibile) con la radio Bluetooth della UNO Q.
    Usa `btmgmt` di BlueZ (serve root o CAP_NET_ADMIN). Il beacon resta attivo e viene
    aggiornato a ogni nuovo messaggio; quando MQTT torna sano viene spento con idle()."""

    INSTANCE = "1"
    kind = "ble"

    def __init__(self, sudo=False, runner=None):
        self.prefix = ["sudo"] if sudo else []
        self.run = runner or self._run
        self.active = False
        self.last_frame = None
        self.run(["btmgmt", "power", "on"])

    def _run(self, args):
        try:
            r = subprocess.run(self.prefix + args, capture_output=True, text=True, timeout=5)
            if r.returncode != 0:
                log.error("BLE: %s -> %s", " ".join(map(shlex.quote, args)), (r.stderr or r.stdout).strip())
            return r.returncode == 0
        except (OSError, subprocess.TimeoutExpired) as e:
            log.error("BLE non disponibile (%s): verifica `which btmgmt` e i permessi", e)
            return False

    @staticmethod
    def adv_data(frame: bytes) -> str:
        """Struttura AD 'Manufacturer Specific Data' (tipo 0xFF): len | 0xFF | company_id LE | frame."""
        ad = bytes([1 + 2 + len(frame), 0xFF]) + struct.pack("<H", BLE_COMPANY_ID) + frame
        assert len(ad) <= 31
        return ad.hex()

    def send(self, payload: bytes, port: int = PORT_AGGREGATE) -> bool:
        frame = ble_frame(payload, port)
        self.run(["btmgmt", "rm-adv", self.INSTANCE])
        ok = self.run(["btmgmt", "add-adv", "-d", self.adv_data(frame), self.INSTANCE])
        if ok:
            self.active, self.last_frame = True, frame
            log.info("[BLE] beacon aggiornato (%d byte): %s", len(frame), frame.hex().upper())
        return ok

    def idle(self):
        if self.active:
            self.run(["btmgmt", "rm-adv", self.INSTANCE])
            self.active = False
            log.info("[BLE] beacon spento: MQTT di nuovo sano")


class NoBackup:
    kind, active = "none", False

    def send(self, payload, port=PORT_AGGREGATE):
        return False

    def idle(self):
        pass


def make_backup(kind: str, mcu, ble_sudo=False):
    kind = (kind or "lora").lower()
    if kind == "ble":
        return BleBackup(sudo=ble_sudo) if ON_UNO_Q else SimulatedBle()
    if kind == "none":
        return NoBackup()
    return McuLoraBackup(mcu)


class SimulatedBle(BleBackup):
    """BLE simulato sul laptop: costruisce gli stessi comandi btmgmt ma non li esegue."""

    def __init__(self):
        self.commands = []
        super().__init__(runner=lambda args: self.commands.append(args) or True)
