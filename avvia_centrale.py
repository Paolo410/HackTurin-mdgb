#!/usr/bin/env python3
"""One command to start the MDGB central on any PC of the team and let the board find it.

    python avvia_centrale.py        (python3 on Mac and Linux; from the folder of the repository)

What it does:
1. first run only: makes app/.venv and installs what the central needs (the requirements of app/, the
   window, and zeroconf for the name on the network);
2. announces on the local network that THIS PC is "mdgb-centrale.local" (mDNS). The board is set once on
   that name (MQTT_HOST=mdgb-centrale.local in comms/.env on the board) and from then on follows whichever
   PC runs this command: no IP address to change when the network or the PC changes, no access to the
   board needed;
3. starts the central of app/ as it is (Mosquitto broker + dashboard + window) with the dashboard open to
   the local network, and prints the addresses.

Only one PC at a time can be the central. Closing the window (or Ctrl+C) stops everything.
The only thing to install by hand is the broker Mosquitto: "brew install mosquitto" on a Mac,
https://mosquitto.org/download/ on Windows, "sudo apt install mosquitto" on Linux.

Options:
    --solo-questo-pc    the dashboard answers only on this PC (default: also to phones and PCs on the network)
    --senza-bluetooth   do not listen to the Bluetooth backup of the nodes (if this PC has no Bluetooth)
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"
VENV = APP / ".venv"                                   # ignored by git
VENV_PYTHON = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
CENTRAL_NAME = "mdgb-centrale.local"                   # what the board has in MQTT_HOST
MQTT_PORT = 1883
ZEROCONF = "zeroconf==0.151.5"                         # mDNS announcement, pure Python, all systems
NOT_TO_RUN = ("pyinstaller",)                          # in app/desktop/requirements.txt only to build the app
MIN_PYTHON = (3, 10)
WEB_PORT_TRIES = 20                                    # ports tried after the configured one, if it is busy


def desktop_requirements() -> list[str]:
    """The lines of app/desktop/requirements.txt that are needed to run the central (not to build it)."""
    wanted = []
    for line in (APP / "desktop" / "requirements.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-r") and not line.lower().startswith(NOT_TO_RUN):
            wanted.append(line)
    return wanted


def prepare_environment() -> None:
    """Makes app/.venv on the first run and installs the libraries; later runs only check and go on."""
    if not VENV_PYTHON.exists():
        print("Primo avvio: preparo l'ambiente Python in app/.venv (serve Internet, un paio di minuti)...")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    stamp = VENV / ".mdgb-installed"
    wanted = "\n".join([(APP / "requirements.txt").read_text(encoding="utf-8"), *desktop_requirements(), ZEROCONF])
    if not stamp.exists() or stamp.read_text(encoding="utf-8") != wanted:
        subprocess.check_call([str(VENV_PYTHON), "-m", "pip", "install", "-q", "--disable-pip-version-check",
                               "-r", str(APP / "requirements.txt"), *desktop_requirements(), ZEROCONF])
        stamp.write_text(wanted, encoding="utf-8")


def local_ip() -> str:
    """The address of this PC on the network it uses to go out (no packet is sent)."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.connect(("192.0.2.1", 9))
        return s.getsockname()[0]


def port_free(port: int) -> bool:
    """True if nothing on this PC is listening on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        if s.connect_ex(("127.0.0.1", port)) == 0:
            return False
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(("0.0.0.0", port))
        except OSError:
            return False
    return True


def prepare_settings(config: Path, lan: bool, bluetooth: bool) -> None:
    """Sets in the settings of the central: who can open the dashboard, a free port for it, the Bluetooth
    if asked. Everything else is left as it is."""
    text = config.read_text(encoding="utf-8")
    new = re.sub(r"(?m)^WEB_HOST=.*$", "WEB_HOST=" + ("0.0.0.0" if lan else "127.0.0.1"), text)
    if not bluetooth:
        new = re.sub(r"(?m)^BLE=.*$", "BLE=0", new)
    port = int(re.search(r"(?m)^WEB_PORT=(\d+)", new).group(1))
    if not port_free(port):                              # another program of this PC already uses it
        free = next((p for p in range(port + 1, port + WEB_PORT_TRIES) if port_free(p)), None)
        if free is not None:
            print(f"La porta {port} di questo PC è occupata da un altro programma: la dashboard usa la {free}.")
            new = re.sub(r"(?m)^WEB_PORT=.*$", f"WEB_PORT={free}", new)
    if new != text:
        config.write_text(new, encoding="utf-8")


def main() -> int:
    if sys.version_info < MIN_PYTHON:
        print(f"Serve Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} o più recente (questo è {sys.version.split()[0]}).")
        return 2
    if Path(sys.prefix).resolve() != VENV.resolve():     # not yet inside app/.venv
        prepare_environment()
        # Run again with the Python of the environment, which has the libraries.
        return subprocess.call([str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])

    sys.path.insert(0, str(APP / "desktop"))
    import centrale_app                                  # the launcher of app/: used as it is
    from zeroconf import ServiceInfo, Zeroconf

    if centrale_app.find_mosquitto() is None:
        print("Manca il broker Mosquitto. Mac: brew install mosquitto   Windows: https://mosquitto.org/download/   "
              "Linux: sudo apt install mosquitto. Poi rilancia.")
        return 2
    home = centrale_app.home_dir()
    lan = "--solo-questo-pc" not in sys.argv
    prepare_settings(Path(centrale_app.prepare_home(home)), lan, "--senza-bluetooth" not in sys.argv)
    config = centrale_app.read_config(os.path.join(home, "config.env"))
    web_port = config.get("WEB_PORT", "8080")

    ip = local_ip()
    # A service whose host name is ours: on the network "mdgb-centrale.local" now answers with this PC.
    info = ServiceInfo("_mqtt._tcp.local.", "MDGB Centrale._mqtt._tcp.local.", addresses=[socket.inet_aton(ip)],
                       port=MQTT_PORT, server=CENTRAL_NAME + ".")
    announcer = Zeroconf(interfaces=[ip])
    announcer.register_service(info)
    print(f"\nMDGB Centrale su questo PC ({ip}).")
    print(f"  Per la scheda questo PC è {CENTRAL_NAME}:{MQTT_PORT} (annunciato in rete finché questa finestra resta aperta).")
    print(f"  Dashboard: http://localhost:{web_port}" + (f"   dagli altri PC e dal telefono: http://{ip}:{web_port}" if lan else ""))
    print(f"  Impostazioni e dati: {home}")
    print(f"  Sulla scheda, una volta sola: MQTT_HOST={CENTRAL_NAME} in ~/HackTurin-mdgb/comms/.env, poi "
          "sudo systemctl restart mdgb-comms\n")
    try:
        return subprocess.call([sys.executable, str(APP / "desktop" / "centrale_app.py")])
    except KeyboardInterrupt:
        return 0
    finally:
        announcer.unregister_service(info)
        announcer.close()


if __name__ == "__main__":
    sys.exit(main())
