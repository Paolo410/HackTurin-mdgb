# PyInstaller: ricetta dell'app "MDGB Centrale". Non si lancia a mano: build_mac.sh (macOS) o build_windows.ps1 (Windows).
#   macOS   -> "MDGB Centrale.app"
#   Windows -> "MDGB Centrale.exe" (un solo file)
import glob
import os
import shutil
import sys

from PyInstaller.utils.hooks import collect_submodules

WIN = sys.platform.startswith("win")
HERE = os.path.dirname(os.path.abspath(SPEC))      # noqa: F821  (SPEC lo definisce PyInstaller)
APP = os.path.dirname(HERE)
ICON = os.path.join(HERE, "build", "icon.ico" if WIN else "icon.icns")

# Il broker Mosquitto va DENTRO l'app (con le sue librerie): il centralino non deve installare nulla.
if WIN:
    MOSQ_DIR = os.environ.get("MOSQUITTO_DIR", r"C:\Program Files\mosquitto")
    MOSQ = os.path.join(MOSQ_DIR, "mosquitto.exe")
    extra = [(dll, "mosquitto") for dll in glob.glob(os.path.join(MOSQ_DIR, "*.dll"))]   # OpenSSL e simili
    # runtime Visual C++ accanto a mosquitto.exe: non è garantito che ci sia su ogni PC Windows
    have = {os.path.basename(d).lower() for d, _ in extra}
    for name in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll"):
        for folder in (sys.base_prefix, os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32")):
            path = os.path.join(folder, name)
            if name not in have and os.path.exists(path):
                extra.append((path, "mosquitto"))
                have.add(name)
else:
    MOSQ = shutil.which("mosquitto") or "/opt/homebrew/sbin/mosquitto"
    extra = []
if not os.path.exists(MOSQ):
    raise SystemExit(f"Mosquitto non trovato ({MOSQ}): installalo prima della build (vedi build_mac.sh / build_windows.ps1)")

hidden = ["central", "ingest", "dashboard", "decoder", "diagnosis", "ble_receiver", "customers", "publisher"] \
    + collect_submodules("bleak")
# modello del flusso atteso (ai/forecast, owner Paolo): solo i moduli di runtime, che usano la libreria standard
AI = os.path.join(os.path.dirname(APP), "ai")
hidden += ["forecast." + m for m in ("service", "context", "sources", "features", "fusion", "model", "analytics")] + ["certifi"]
if WIN:
    hidden += ["clr"] + collect_submodules("winrt")   # finestra (pythonnet) e Bluetooth (WinRT) su Windows

a = Analysis(
    [os.path.join(HERE, "centrale_app.py")],
    pathex=[APP, AI],
    binaries=[(os.path.realpath(MOSQ), "mosquitto")] + extra,
    datas=[(os.path.join(APP, "dashboard.html"), "."), (os.path.join(APP, "nodes.json"), "."),
           (os.path.join(AI, "forecast", "model.json"), "forecast")],
    hiddenimports=hidden,
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)

if WIN:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, name="MDGB Centrale", console=False,
              icon=ICON if os.path.exists(ICON) else None)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="MDGB Centrale", console=False)
    coll = COLLECT(exe, a.binaries, a.datas, name="MDGB Centrale")
    app = BUNDLE(
        coll,
        name="MDGB Centrale.app",
        icon=ICON if os.path.exists(ICON) else None,
        bundle_identifier="it.hackturin.mdgb.centrale",
        info_plist={
            "CFBundleDisplayName": "MDGB Centrale",
            "CFBundleShortVersionString": "1.0",
            "LSMinimumSystemVersion": "12.0",
            "NSHighResolutionCapable": True,
            # senza questa riga macOS chiude l'app al primo accesso al Bluetooth
            "NSBluetoothAlwaysUsageDescription":
                "MDGB Centrale ascolta i beacon Bluetooth dei nodi quando la loro rete Wi-Fi è giù.",
        },
    )
