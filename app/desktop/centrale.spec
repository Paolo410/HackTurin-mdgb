# PyInstaller: ricetta di "MDGB Centrale.app" (macOS). Non si lancia a mano: usa build_mac.sh.
import os

HERE = os.path.dirname(os.path.abspath(SPEC))      # noqa: F821  (SPEC lo definisce PyInstaller)
APP = os.path.dirname(HERE)
ICON = os.path.join(HERE, "build", "icon.icns")

a = Analysis(
    [os.path.join(HERE, "centrale_app.py")],
    pathex=[APP],
    datas=[(os.path.join(APP, "dashboard.html"), "."), (os.path.join(APP, "nodes.json"), ".")],
    hiddenimports=["central", "ingest", "dashboard", "decoder", "diagnosis", "ble_receiver"],
    excludes=["tkinter"],
)
pyz = PYZ(a.pure)
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
