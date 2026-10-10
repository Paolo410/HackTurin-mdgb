"""Status page for the technician at the crossing: numbers and state only, never images.

A phone on the same network opens http://<board>:<port>/ . The page answers only for operator.unlock_s
after the technician's badge (McuState.unlocked); before that it says to show the badge.
Privacy: nothing here can show a person. It is the same metadata that goes to the central (C3), plus the
readings of the microcontroller. No frame is ever kept or sent.
Standard library only (http.server): no new dependency on the board.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PAGE = """<!doctype html>
<html lang="it"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>MDGB - stato del nodo</title>
<style>
body{margin:0;padding:16px;font:16px/1.45 -apple-system,"Segoe UI",Roboto,Arial,sans-serif;background:#10151a;color:#e8edf0}
h1{font-size:20px;margin:0 0 4px}#state{font-size:34px;font-weight:700;margin:10px 0 2px}
#reason{color:#aab6bd;margin:0 0 14px}table{border-collapse:collapse;width:100%;max-width:520px}
td{padding:6px 4px;border-bottom:1px solid #2a343b}td:last-child{text-align:right;font-variant-numeric:tabular-nums}
.warn{color:#ffb454}.muted{color:#aab6bd;font-size:14px;margin-top:14px}
</style></head><body>
<h1>MDGB &middot; stato del nodo</h1>
<div id="locked" hidden><p id="state" class="warn">BLOCCATO</p><p>Passa il badge del tecnico sul lettore.</p></div>
<div id="open" hidden><p id="state2"></p><p id="reason"></p><table id="rows"></table>
<p class="muted">Solo numeri: questa pagina non mostra immagini. Si richiude da sola fra <span id="left"></span>.</p></div>
<script>
function row(k, v) { return "<tr><td>" + k + "</td><td>" + (v === null || v === undefined ? "-" : v) + "</td></tr>"; }
async function tick() {
  try {
    const r = await fetch("status.json", {cache: "no-store"});
    const locked = r.status !== 200;
    document.getElementById("locked").hidden = !locked;
    document.getElementById("open").hidden = locked;
    if (locked) return;
    const s = await r.json(), m = s.mcu || {}, e = m.env || {}, l = s.lat_ms || {};
    document.getElementById("state2").innerHTML = "<span id='state'" + (s.state === "DEGRADED" ? " class='warn'" : "") + ">" + s.state + "</span>";
    document.getElementById("reason").textContent = s.reason || "";
    let h = row("Lampada richiesta", s.led) + row("Verde pedonale richiesto", s.green_s + " s");
    h += row("Semaforo (firmware)", s.link_failsafe ? "ciclo normale: nessun collegamento" : "collegato alla visione");
    h += row("Fotogrammi al secondo", s.fps) + row("Tempi (ms)", "detect " + l.detect + " / track " + l.track + " / regole " + l.rules);
    h += row("Tracce valide", s.tracks) + row("Conteggi", s.counts) + row("Eventi", s.events);
    h += row("Temperatura", e.t_c === undefined ? null : e.t_c + " &deg;C") + row("Umidit&agrave;", e.rh === undefined ? null : e.rh + " %");
    h += row("Luce (0-1023)", e.light) + row("eCO2", e.eco2_ppm === undefined ? null : e.eco2_ppm + " ppm");
    h += row("Manomissione", m.fault === "tamper" ? "<span class='warn'>urto " + m.tamper_s_ago + " s fa: verifica la camera, poi ripassa il badge</span>" : "no");
    h += row("Ultimo fail-safe del firmware", m.firmware_failsafe ? m.firmware_failsafe.reason + ", " + m.firmware_failsafe.s_ago + " s fa" : "nessuno");
    h += row("Acceso da", Math.round(s.uptime_s / 60) + " min") + row("Camera", s.source) + row("Calibrazione", s.calib);
    document.getElementById("rows").innerHTML = h;
    document.getElementById("left").textContent = Math.ceil(m.unlock_s_left / 60) + " min";
  } catch (err) { /* the board is restarting: try again */ }
}
tick(); setInterval(tick, 1000);
</script></body></html>
"""


class OperatorPage:
    """Small HTTP server in its own threads. The vision loop only calls update(), which never blocks."""

    def __init__(self, port: int, mcu, host: str = "0.0.0.0"):
        self.mcu = mcu
        self._status: dict = {}
        self._started = time.monotonic()
        page = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (name fixed by http.server)
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
                elif path == "/status.json":
                    if not page.mcu.unlocked():
                        self._send(403, "application/json", b'{"locked":true}')
                    else:
                        self._send(200, "application/json", json.dumps(page.status()).encode("utf-8"))
                else:
                    self._send(404, "text/plain", b"not found")

            def _send(self, code: int, content_type: str, body: bytes) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args) -> None:
                pass   # one line per request would bury the status lines of the vision

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, name="mdgb-operator", daemon=True)
        self._thread.start()

    def update(self, status: dict) -> None:
        """Called by the vision loop with the numbers of the last frame (a plain dict of text and numbers)."""
        self._status = status

    def status(self) -> dict:
        return {**self._status, "uptime_s": round(time.monotonic() - self._started), "mcu": self.mcu.snapshot()}

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
