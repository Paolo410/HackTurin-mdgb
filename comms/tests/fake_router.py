"""Stand-in for the arduino-router of the UNO Q plus the sketch, to test BridgeActuator on a PC with the real
arduino-router-bridge library. Same wire format as the router: MessagePack-RPC over a unix socket
([0, id, method, params] request, [1, id, error, result] response, [2, method, params] notification;
clients register the methods they provide with the "$/register" call).
https://github.com/arduino/arduino-router-bridge-py (protocol.py, connection.py)

The "sketch" provides mdgb_line like firmware/unoq_mcu must: it returns true for a valid C1/C2 line.
"""
import json
import os
import socket
import tempfile
import threading

import msgpack

REQUEST, RESPONSE, NOTIFICATION = 0, 1, 2
METHOD_NOT_AVAILABLE, ROUTE_ALREADY_EXISTS = 2, 5


class FakeRouter:
    def __init__(self, sketch_loaded=True):
        self.dir = tempfile.mkdtemp(prefix="mdgb-rt-", dir="/tmp" if os.path.isdir("/tmp") else None)
        self.path = os.path.join(self.dir, "router.sock")     # short: unix socket paths are limited to ~104 bytes
        self.address = "unix://" + self.path
        self.sketch_loaded = sketch_loaded
        self.lines = []                 # what the sketch received through mdgb_line, parsed
        self.routes = {}                # method -> client socket that provides it
        self._clients = []
        self._lock = threading.Lock()
        self._srv = None

    def start(self):
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(self.path)
        self._srv.listen()
        threading.Thread(target=self._accept, args=(self._srv,), daemon=True).start()
        return self

    def stop(self):
        srv, self._srv = self._srv, None
        if srv is not None:
            srv.close()
        with self._lock:
            for c in self._clients:
                try:
                    c.shutdown(socket.SHUT_RDWR)
                    c.close()
                except OSError:
                    pass
            self._clients.clear()
            self.routes.clear()
        if os.path.exists(self.path):
            os.unlink(self.path)

    def mcu_notify(self, method, *params):
        """The sketch calls Bridge.notify(method, ...): forwarded to the client that provides it."""
        with self._lock:
            c = self.routes.get(method)
        if c is None:
            return False
        c.sendall(msgpack.packb([NOTIFICATION, method, list(params)]))
        return True

    # ---------- internals ----------
    def _accept(self, srv):
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            with self._lock:
                self._clients.append(c)
            threading.Thread(target=self._serve, args=(c,), daemon=True).start()

    def _serve(self, c):
        unpacker = msgpack.Unpacker(raw=False)
        while True:
            try:
                data = c.recv(65536)
            except OSError:
                data = b""
            if not data:
                with self._lock:
                    for m in [m for m, s in self.routes.items() if s is c]:
                        del self.routes[m]
                return
            unpacker.feed(data)
            for msg in unpacker:
                if msg[0] == REQUEST:
                    _, msgid, method, params = msg
                    err, result = self._handle(c, method, params)
                    c.sendall(msgpack.packb([RESPONSE, msgid, err, result]))

    def _handle(self, c, method, params):
        if method == "$/register":
            with self._lock:
                owner = self.routes.get(params[0])
                if owner is not None and owner is not c:
                    return [ROUTE_ALREADY_EXISTS, "route already exists"], None
                self.routes[params[0]] = c
            return None, True
        if method == "mdgb_line" and self.sketch_loaded:
            try:
                obj = json.loads(params[0])
            except (ValueError, TypeError):
                return None, False
            if not isinstance(obj, dict) or obj.get("v") != 1:
                return None, False
            self.lines.append(obj)
            return None, True
        return [METHOD_NOT_AVAILABLE, f"method {method} not available"], None
