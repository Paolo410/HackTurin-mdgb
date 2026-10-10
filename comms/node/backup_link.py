"""Canale di backup del nodo: BLE (radio della UNO Q, demo) oppure LoRa (modulo sull'MCU, produzione).

BLE:  Python (Linux) --btmgmt (BlueZ)--> radio Bluetooth della UNO Q --> beacon ricevuti dal PC della centrale
LoRa: Python (Linux) --Bridge.call("lora_send")--> sketch MCU --UART--> modulo LoRa (Wio-E5)
Niente simulazioni qui: se la radio scelta non c'è il nodo si ferma con un errore chiaro (le prove senza scheda
usano i finti di comms/tests/fakes.py).
"""
import logging
import shlex
import shutil
import struct
import subprocess

log = logging.getLogger("mcu")


class McuLink:
    """Funzioni esposte dallo sketch con Bridge.provide(...) (docs/CONTRACTS.md v1, sezione Bridge).
    C1/C2 verso l'MCU passano da comms/actuators.py: qui serve solo la radio LoRa (produzione).
    Client ufficiale dell'arduino-router, lo stesso di App Lab, usabile da un venv normale:
    https://github.com/arduino/arduino-router-bridge-py"""

    CALL_TIMEOUT_S = 2.0

    def __init__(self, address=None, bridge=None):
        if bridge is None:
            from arduino.router_bridge import DEFAULT_ADDRESS, Bridge   # pip: arduino-router-bridge
            bridge = Bridge(address or DEFAULT_ADDRESS)
            if not bridge.connect(timeout=5):
                log.error("arduino-router non raggiungibile: riprovo in background (systemctl status arduino-router)")
        self.bridge = bridge

    def _call(self, name, *args):
        try:
            return self.bridge.call(name, *args, timeout=self.CALL_TIMEOUT_S)
        except Exception as e:                  # l'MCU non deve mai far cadere la pipeline
            log.error("Bridge.call(%s) fallita: %s", name, e)
            return False

    def lora_send(self, payload: bytes, port: int = 1) -> bool:
        """Accoda un uplink LoRa (fPort = type C4-B). Ritorna subito: la trasmissione avviene nel loop() dell'MCU."""
        return bool(self._call("lora_send", int(port), payload.hex().upper()))

    def lora_joined(self) -> bool:
        return bool(self._call("lora_joined"))


# ======================================================================================
# Canale di backup intercambiabile: LoRa (via MCU) oppure BLE (radio integrata nella UNO Q)
#   config.BACKUP_LINK = "lora" | "ble" | "none"
#   Interfaccia comune:  send(payload, port=1) -> bool   |   idle()  (chiamata quando MQTT è sano)
# ======================================================================================

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
    Usa `btmgmt` di BlueZ (serve root o CAP_NET_ADMIN). Fino a tre beacon insieme, uno per tipo di messaggio
    (istanza 1 = AGG, 2 = HB, 3 = allarmi), così un allarme non cancella l'ultimo HB o AGG: BlueZ li trasmette
    a rotazione. Ogni beacon resta acceso e viene aggiornato a ogni nuovo messaggio del suo tipo; quando MQTT torna
    stabile si spengono tutti con idle().
    TODO(verify) sulla UNO Q: rotazione di più istanze con btmgmt add-adv sul controller della scheda."""

    INSTANCES = {1: "1", 2: "2"}       # type C4-B -> istanza; tutti gli altri tipi (allarmi) -> "3"
    ALARM_INSTANCE = "3"
    kind = "ble"

    def __init__(self, sudo=False, runner=None):
        self.prefix = ["sudo"] if sudo else []
        self.run = runner or self._run
        self.active = False
        self.frames = {}                   # istanza -> frame in onda adesso
        if not self.run(["btmgmt", "power", "on"]):
            log.error("BLE: la radio non risponde a btmgmt: avvia il nodo con sudo (o BLE_SUDO=1)")

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
        inst = self.INSTANCES.get(port, self.ALARM_INSTANCE)
        if inst in self.frames:
            self.run(["btmgmt", "rm-adv", inst])
        ok = self.run(["btmgmt", "add-adv", "-d", self.adv_data(frame), inst])
        if ok:
            self.active, self.frames[inst] = True, frame
            log.info("[BLE] beacon %s aggiornato (type %d): %s", inst, port, frame.hex().upper())
        else:
            self.frames.pop(inst, None)
        return ok

    def idle(self):
        if self.active:
            for inst in sorted(self.frames):
                self.run(["btmgmt", "rm-adv", inst])
            self.frames.clear()
            self.active = False
            log.info("[BLE] beacon spenti: MQTT di nuovo stabile")


class NoBackup:
    kind, active = "none", False

    def send(self, payload, port=PORT_AGGREGATE):
        return False

    def idle(self):
        pass


def ble_available() -> bool:
    """BLE vero dove c'è BlueZ: il Linux della UNO Q (anche fuori da App Lab)."""
    return shutil.which("btmgmt") is not None


def make_backup(kind: str, ble_sudo=False, mcu=None):
    """kind = BACKUP_LINK: "ble" | "lora" | "none". Se la radio scelta non c'è -> RuntimeError, mai una finta."""
    kind = (kind or "ble").lower()
    if kind == "ble":
        if not ble_available():
            raise RuntimeError("BACKUP_LINK=ble ma btmgmt non c'è: sulla UNO Q `sudo apt install bluez`. "
                               "Su un PC senza BlueZ usa BACKUP_LINK=none")
        log.info("backup BLE reale (btmgmt)")
        return BleBackup(sudo=ble_sudo)
    if kind == "none":
        log.info("backup spento (BACKUP_LINK=none)")
        return NoBackup()
    if kind == "lora":
        log.info("backup LoRa via MCU (Bridge lora_send)")
        return McuLoraBackup(mcu or McuLink())
    raise ValueError(f"BACKUP_LINK sconosciuto: {kind!r} (ble | lora | none)")
