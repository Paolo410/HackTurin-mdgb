"""Page for the technician at the crossing, reached from a phone on the same Wi-Fi: http://<board>:<port>/

Access needs two things: the technician's badge on the reader, and then within operator.login_s (2 min)
a login with user name and password. Without both, nothing is shown. The session lasts until the
technician logs out (or operator.session_s, if set). From the badge until then the technician is present
(technician_present): the vision tells the sketch, which keeps the buzzer quiet.

What it shows: the numbers (state, reason, FPS, times, counts, sensors) and, if operator.share_images is
true, a live view of what the vision sees. With share_images false no image ever leaves the vision
process: only the statistics remain (the setting for production, for privacy).
Images are live only: they are never written to disk and are produced only while someone is watching.

The credentials are not in the repository: user name and password hash are read from the environment or
from operator.credentials_file (ai/.env, ignored by git), written by scripts/operator_login.py.
Limit: plain HTTP. On the local network the password travels unencrypted; production needs HTTPS.
Standard library only for the server (http.server); OpenCV, already a dependency, for the JPEG.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from collections import deque
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qs

import cv2
import numpy as np

from .config import resolve_path
from .operator_ui import PAGE

USER_VAR, HASH_VAR = "MDGB_OPERATOR_USER", "MDGB_OPERATOR_PASSWORD_HASH"
HASH_NAME, HASH_ITERATIONS = "pbkdf2_sha256", 200_000
COOKIE = "mdgb_session"
MAX_LOGIN_BYTES = 4096               # a login form is a few dozen bytes: anything larger is not a login
_BOUNDARY = b"frame"
LOG_LEN = 100                        # last events kept for the page, in memory only
NOTE_REPEAT_S = 5.0                  # the same line again within this time is dropped (repeated alarms)



def hash_password(password: str, salt: bytes | None = None, iterations: int = HASH_ITERATIONS) -> str:
    """The text stored in place of the password: algorithm$iterations$salt$hash (PBKDF2, standard library)."""
    salt = salt if salt is not None else secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{HASH_NAME}${iterations}${salt.hex()}${digest.hex()}"


def check_password(password: str, stored: str) -> bool:
    try:
        name, iterations, salt, digest = stored.split("$")
        if name != HASH_NAME:
            return False
        again = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iterations))
    except ValueError:
        return False
    return hmac.compare_digest(again.hex(), digest)


def load_credentials(cfg: dict) -> tuple[str, str] | None:
    """(user, password hash) from the environment, else from operator.credentials_file. None = not set up."""
    values = {name: os.environ.get(name, "") for name in (USER_VAR, HASH_VAR)}
    path = resolve_path(cfg["operator"]["credentials_file"])
    if not all(values.values()) and Path(path).is_file():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            name, _, value = line.partition("=")
            if name.strip() in values and not values[name.strip()]:
                values[name.strip()] = value.strip()
    return (values[USER_VAR], values[HASH_VAR]) if all(values.values()) else None


class OperatorPage:
    """Small HTTP server in its own threads. The vision loop only calls update() and, when someone is
    watching, push_frame(): neither waits for the network."""

    def __init__(self, port: int, mcu, cfg: dict, host: str = "0.0.0.0",
                 monotonic: Callable[[], float] = time.monotonic):
        o = cfg["operator"]
        self.mcu = mcu
        self._monotonic = monotonic
        self.credentials = load_credentials(cfg)
        self.share_images = bool(o["share_images"])
        self.max_failed = int(o["max_failed_logins"])
        self.session_s = float(o["session_s"])     # 0 = until logout
        self.login_s = float(o["login_s"])
        self.log: deque = deque(maxlen=LOG_LEN)     # what happened, for the Registro of the page
        self.health: dict = {}                     # last check of the parts of the node (health.py), from the app
        self.stream_period = 1.0 / float(o["stream_fps"])
        self.stream_width = int(o["stream_width"])
        self.jpeg_quality = int(o["jpeg_quality"])
        self._status: dict = {}
        self._started = time.monotonic()
        self._lock = threading.Lock()
        self._sessions: dict[str, float] = {}     # session token -> monotonic time it ends (inf = at logout)
        # Set by the app when the source is a recorded video: called with "prev", "next", "back" or "fwd".
        self.video_control: Callable[[str], bool] | None = None
        self._badges_seen = mcu.badges
        self._failed = 0
        self._failed_window = -1
        self._viewers = 0
        self._frame_ready = threading.Condition()
        self._jpeg: bytes | None = None
        self._jpeg_n = 0
        self._last_push = -float("inf")
        self._closed = False
        page = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802 (name fixed by http.server)
                path = self.path.split("?", 1)[0]
                if path in ("/", "/index.html"):
                    self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
                elif path == "/status.json":
                    code = page.access(self._token())
                    body = (page.status(self._token()) if code == 200 else
                            {"locked": code == 403, "login": code == 401, "login_s_left": page.login_s_left(),
                             "login_s": page.login_s})
                    self._send(code, "application/json", json.dumps(body).encode("utf-8"))
                elif path == "/stream.mjpg":
                    code = page.access(self._token())
                    if code == 200 and not page.share_images:
                        code = 404                 # images switched off: this address does not exist
                    if code != 200:
                        self._send(code, "text/plain", b"")
                    else:
                        self._stream()
                else:
                    self._send(404, "text/plain", b"not found")

            def do_POST(self):  # noqa: N802
                path = self.path.split("?", 1)[0]
                if path == "/login":
                    length = int(self.headers.get("Content-Length") or 0)
                    if not 0 < length <= MAX_LOGIN_BYTES:
                        return self._send(400, "text/plain", b"")
                    form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
                    code, token = page.login(form.get("user", [""])[0], form.get("password", [""])[0])
                    cookie = f"{COOKIE}={token}; HttpOnly; SameSite=Strict; Path=/" if token else None
                    self._send(code, "text/plain", b"", cookie)
                elif path == "/logout":
                    page.logout(self._token())
                    self._send(200, "text/plain", b"", f"{COOKIE}=; Max-Age=0; Path=/")
                elif path == "/video":                 # previous / next video, back / forward (videos only)
                    code = page.access(self._token())
                    length = int(self.headers.get("Content-Length") or 0)
                    action = (parse_qs(self.rfile.read(length).decode("utf-8", "replace")).get("action", [""])[0]
                              if 0 < length <= MAX_LOGIN_BYTES else "")
                    if code == 200:
                        code = 404 if page.video_control is None else 200 if page.video_control(action) else 400
                    self._send(code, "text/plain", b"")
                else:
                    self._send(404, "text/plain", b"not found")

            def _token(self) -> str:
                try:
                    morsel = SimpleCookie(self.headers.get("Cookie", "")).get(COOKIE)
                except CookieError:
                    return ""
                return morsel.value if morsel else ""

            def _send(self, code: int, content_type: str, body: bytes, cookie: str | None = None) -> None:
                self.send_response(code)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                self.end_headers()
                self.wfile.write(body)

            def _stream(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={_BOUNDARY.decode()}")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                token, seen = self._token(), -1
                with page.watching():
                    try:
                        while page.access(token) == 200 and page.share_images:
                            jpeg, seen = page.next_jpeg(seen)
                            if jpeg is None:
                                continue           # no new frame yet: check again that the session is still valid
                            self.wfile.write(b"--" + _BOUNDARY + b"\r\nContent-Type: image/jpeg\r\nContent-Length: "
                                             + str(len(jpeg)).encode() + b"\r\n\r\n" + jpeg + b"\r\n")
                    except OSError:
                        pass                       # the phone went away

            def log_message(self, *_args) -> None:
                pass   # one line per request would bury the status lines of the vision

        self._server = ThreadingHTTPServer((host, port), Handler)
        self._server.daemon_threads = True
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, name="mdgb-operator", daemon=True)
        self._thread.start()

    # ---- access: badge first, then credentials

    def access(self, token: str) -> int:
        """200 = logged in, 401 = badge only (log in), 403 = no badge (or the time to log in is over)."""
        with self._lock:
            self._refresh()
            if token and token in self._sessions:
                return 200
        return 401 if self.mcu.unlocked() else 403

    def login(self, user: str, password: str) -> tuple[int, str | None]:
        """(HTTP code, session token). Too many wrong attempts close the page until the next badge."""
        if not self.mcu.unlocked():
            return 403, None
        if self.credentials is None:
            return 503, None
        window = self.mcu.window
        with self._lock:
            if self._failed_window != window:      # a new badge window starts a new count
                self._failed, self._failed_window = 0, window
            if self._failed >= self.max_failed:
                return 403, None
        good = hmac.compare_digest(user.encode(), self.credentials[0].encode()) & check_password(password, self.credentials[1])
        with self._lock:
            if not good:
                self._failed += 1
                closed = self._failed >= self.max_failed
                if closed:
                    self.mcu.lock()
            else:
                token = secrets.token_urlsafe(32)
                self._sessions[token] = self._session_end()
                self.mcu.lock()                    # the badge is used: the next login needs a new one
        # The Registro outside the lock: note() takes it again.
        if not good:
            self.note("rfid", "troppe password sbagliate: serve un altro badge" if closed
                      else "utente o password sbagliati")
            return 401, None
        self.note("rfid", "il tecnico è entrato")
        return 200, token

    def logout(self, token: str) -> None:
        with self._lock:
            if self._sessions.pop(token, None) is not None and not self._sessions:
                self.mcu.lock()                    # the technician is done: the buzzer is back at once
                left = True
            else:
                left = False
        if left:
            self.note("rfid", "il tecnico è uscito")

    def technician_present(self) -> bool:
        """From the badge to the logout (or the end of the time to log in): the sketch keeps the buzzer quiet."""
        with self._lock:
            self._refresh()
            return bool(self._sessions) or self.mcu.unlocked()

    def login_s_left(self) -> int:
        return self.mcu.snapshot()["login_s_left"]

    def _session_end(self) -> float:
        return self._monotonic() + self.session_s if self.session_s > 0 else float("inf")

    def _refresh(self) -> None:
        """Drops the sessions that are over; a badge while logged in starts them again. Call with the lock."""
        now = self._monotonic()
        for token in [t for t, end in self._sessions.items() if end <= now]:
            del self._sessions[token]
        badges = self.mcu.badges
        if badges != self._badges_seen:
            self._badges_seen = badges
            if self._sessions:                     # already in: more time, no second window to log in
                self._sessions = dict.fromkeys(self._sessions, self._session_end())
                self.mcu.lock()

    # ---- numbers

    def note(self, kind: str, text: str) -> None:
        """One line of the Registro of the page (alarms, badge, crossings, checks). Memory only, never written.
        The same line again within NOTE_REPEAT_S is dropped: the anti-theft alarm repeats every 500 ms."""
        now = time.time()
        with self._lock:
            last = self.log[-1] if self.log else None
            if last and last["type"] == kind and last["text"] == text and now - last["ts"] < NOTE_REPEAT_S:
                return
            self.log.append({"ts": round(now, 1), "type": kind, "text": text})

    def update(self, status: dict) -> None:
        """Called by the vision loop with the numbers of the last frame (a plain dict of text and numbers)."""
        self._status = status

    def status(self, token: str = "") -> dict:
        now = self._monotonic()
        with self._lock:
            end = self._sessions.get(token, now)
        left = None if end == float("inf") else round(max(0.0, end - now))   # None = until logout
        with self._lock:
            log = list(self.log)
        return {**self._status, "uptime_s": round(now - self._started), "mcu": self.mcu.snapshot(),
                "images": self.share_images, "session_s_left": left, "health": self.health, "log": log}

    # ---- live view (only if operator.share_images, only while a logged-in technician is watching)

    def wants_frame(self) -> bool:
        """True when the vision loop should draw and hand over a frame now."""
        return (self.share_images and self._viewers > 0
                and time.monotonic() - self._last_push >= self.stream_period)

    def push_frame(self, view: np.ndarray) -> None:
        """The annotated frame for whoever is watching. Kept in memory only, replaced by the next one."""
        self._last_push = time.monotonic()
        height, width = view.shape[:2]
        if width > self.stream_width:
            view = cv2.resize(view, (self.stream_width, round(height * self.stream_width / width)),
                              interpolation=cv2.INTER_AREA)
        ok, data = cv2.imencode(".jpg", view, [cv2.IMWRITE_JPEG_QUALITY, self.jpeg_quality])
        if ok:
            with self._frame_ready:
                self._jpeg, self._jpeg_n = data.tobytes(), self._jpeg_n + 1
                self._frame_ready.notify_all()

    def watching(self):
        page = self

        class _Viewer:
            def __enter__(self):
                with page._lock:
                    page._viewers += 1

            def __exit__(self, *_exc):
                with page._lock:
                    page._viewers -= 1
                    if page._viewers == 0:
                        page._jpeg = None          # nobody is watching: no image is kept
        return _Viewer()

    def next_jpeg(self, seen: int, timeout: float = 1.0) -> tuple[bytes | None, int]:
        with self._frame_ready:
            if self._jpeg_n == seen and not self._closed:
                self._frame_ready.wait(timeout)
            if self._jpeg is None or self._jpeg_n == seen or self._closed:
                return None, seen
            return self._jpeg, self._jpeg_n

    def close(self) -> None:
        with self._frame_ready:
            self._closed = True
            self._frame_ready.notify_all()
        self._server.shutdown()
        self._server.server_close()
