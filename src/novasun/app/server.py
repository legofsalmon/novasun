"""A local HTTP service over the application state, plus the browser UI.

Standard library only, like the rest of this repository, so it runs anywhere
Python does with nothing to install. The split is deliberate: state lives in
:mod:`novasun.app.state`, this module only exposes it. A different front end --
Electron, Tauri, a native app -- can talk to the same endpoints, or import the
state layer directly and skip HTTP entirely.

Endpoints:

===========================  ======  ==============================================
``/``                        GET     the browser UI
``/api/state``               GET     everything: devices, status, recent actions
``/api/devices``             POST    ``{"address": "..."}`` add a device
``/api/devices/<address>``   DELETE  forget a device
``/api/discover``            POST    broadcast for devices and add what answers
``/api/refresh``             POST    refresh now rather than waiting for the tick
``/api/action``              POST    ``{"address", "action", ...arguments}``
``/api/screens``             POST    ``{"name", "members": [...]}`` define a screen
``/api/screens/<id>``        POST    update a screen's name, note or members
``/api/screens/<id>``        DELETE  forget a screen
``/api/screens/<id>/action`` POST    run an action across the whole screen
``/api/alerts/acknowledge``  POST    ``{"key": "..."}`` silence without dismissing
``/api/thresholds``          POST    update alert thresholds
===========================  ======  ==============================================

**Binds to localhost by default.** This service holds control sessions to live
screens and has no authentication; exposing it on a network interface would let
anyone on that network black out a wall. ``--host`` will do it anyway, and warns.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .screens import ScreenMember
from .state import Application

DEFAULT_PORT = 8770
UI_PATH = Path(__file__).with_name("ui.html")


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "novasun"

    @property
    def app(self) -> Application:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, *args: Any) -> None:
        if getattr(self.server, "verbose", False):
            super().log_message(*args)

    # --- plumbing -----------------------------------------------------------

    def _send(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, text: str) -> None:
        body = text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            value = json.loads(self.rfile.read(length))
        except json.JSONDecodeError:
            return {}
        return value if isinstance(value, dict) else {}

    # --- routes -------------------------------------------------------------

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/") or "/"
        if path == "/":
            return self._send_html(_ui_source())
        if path == "/api/state":
            return self._send(self.app.snapshot())
        self._send({"error": "not found"}, 404)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")
        body = self._body()

        if path == "/api/devices":
            address = str(body.get("address", "")).strip()
            if not address:
                return self._send({"error": "an address is required"}, 400)
            self.app.add(address)
            return self._send(self.app.snapshot())

        if path == "/api/discover":
            found = self.app.discover()
            return self._send({"found": found, "state": self.app.snapshot()})

        if path == "/api/refresh":
            self.app.refresh_all()
            return self._send(self.app.snapshot())

        if path == "/api/screens":
            name = str(body.get("name", "")).strip()
            if not name:
                return self._send({"error": "a name is required"}, 400)
            members = [ScreenMember.from_dict(m) for m in body.get("members", [])]
            screen = self.app.add_screen(name, members)
            return self._send({"screen": screen.to_dict(), "state": self.app.snapshot()})

        if path.startswith("/api/screens/") and path.endswith("/action"):
            identifier = path[len("/api/screens/") : -len("/action")]
            action = str(body.pop("action", ""))
            if not action:
                return self._send({"error": "an action is required"}, 400)
            records = self.app.execute_screen(identifier, action, **body)
            ok = all(record.ok for record in records)
            return self._send(
                {
                    "results": [record.to_dict() for record in records],
                    "state": self.app.snapshot(),
                },
                200 if ok else 409,
            )

        if path.startswith("/api/screens/"):
            identifier = path[len("/api/screens/") :]
            screen = self.app.update_screen(identifier, **body)
            if screen is None:
                return self._send({"error": "no such screen"}, 404)
            return self._send({"screen": screen.to_dict(), "state": self.app.snapshot()})

        if path == "/api/alerts/acknowledge":
            key = str(body.get("key", ""))
            if not self.app.acknowledge(key):
                return self._send({"error": "no such alert"}, 404)
            return self._send(self.app.snapshot())

        if path == "/api/thresholds":
            try:
                thresholds = self.app.set_thresholds(**body)
            except (ValueError, TypeError) as exc:
                return self._send({"error": str(exc)}, 400)
            return self._send(
                {"thresholds": thresholds.to_dict(), "state": self.app.snapshot()}
            )

        if path == "/api/action":
            address = str(body.pop("address", ""))
            action = str(body.pop("action", ""))
            if not address or not action:
                return self._send({"error": "address and action are required"}, 400)
            record = self.app.execute(address, action, **body)
            return self._send(
                {"result": record.to_dict(), "state": self.app.snapshot()},
                200 if record.ok else 409,
            )

        self._send({"error": "not found"}, 404)

    def do_DELETE(self) -> None:  # noqa: N802
        path = self.path.split("?")[0].rstrip("/")
        if path.startswith("/api/screens/"):
            if self.app.remove_screen(path[len("/api/screens/") :]):
                return self._send(self.app.snapshot())
            return self._send({"error": "no such screen"}, 404)

        prefix = "/api/devices/"
        if path.startswith(prefix):
            address = path[len(prefix) :]
            if self.app.remove(address):
                return self._send(self.app.snapshot())
            return self._send({"error": "no such device"}, 404)
        self._send({"error": "not found"}, 404)


def _ui_source() -> str:
    try:
        return UI_PATH.read_text()
    except OSError:
        return "<h1>novasun</h1><p>UI file missing; the API is still available.</p>"


class NovasunServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        application: Application,
        host: str = "127.0.0.1",
        port: int = DEFAULT_PORT,
    ) -> None:
        super().__init__((host, port), _Handler)
        self.app = application
        self.verbose = False

    @property
    def address(self) -> tuple[str, int]:
        return self.server_address[0], self.server_address[1]

    def serve_in_thread(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread


def serve(
    hosts: list[str] | None = None,
    host: str = "127.0.0.1",
    port: int = DEFAULT_PORT,
    refresh_interval: float = 10.0,
    discover: bool = False,
    config_path: Path | None = None,
) -> None:
    """Run the application until interrupted, restoring the saved config."""
    application = Application.from_config(config_path)
    application.refresh_interval = refresh_interval
    if application.config_error:
        print(f"  config: {application.config_error}")
    for address in hosts or []:
        application.add(address)
    if discover:
        application.discover()
    application.start()

    server = NovasunServer(application, host, port)
    bound_host, bound_port = server.address
    print(f"novasun on http://{bound_host}:{bound_port}")
    if host not in ("127.0.0.1", "localhost", "::1"):
        print(
            "  WARNING: bound to a non-local interface with no authentication.\n"
            "  Anyone who can reach this port can black out a screen.",
        )
    print(
        f"  {len(application.devices)} device(s), {len(application.screens)} screen(s), "
        f"refreshing every {refresh_interval:g}s"
    )
    if application.config_path:
        print(f"  config {application.config_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        application.stop()
