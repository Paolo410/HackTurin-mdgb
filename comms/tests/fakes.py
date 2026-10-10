"""Test doubles of the node's radios: same interface as the real ones, nothing transmitted.
They live only here: the node on the board never falls back to them."""
import logging

from backup_link import BleBackup

log = logging.getLogger("fakes")


class SimulatedBle(BleBackup):
    """Builds the same btmgmt commands as the real BLE backup but only records them (self.commands)."""

    def __init__(self):
        self.commands = []
        super().__init__(runner=lambda args: self.commands.append(args) or True)


class SimulatedMcu:
    """Same interface as backup_link.McuLink: records the LoRa uplinks instead of sending them."""

    def __init__(self):
        self.sent = []          # (fPort, payload)

    def lora_send(self, payload: bytes, port: int = 1) -> bool:
        self.sent.append((port, payload))
        return True

    def lora_joined(self) -> bool:
        return True
