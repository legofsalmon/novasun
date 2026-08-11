"""A man-in-the-middle proxy that logs NovaLCT's conversation with a controller.

This is the better half of the capture story. Instead of sniffing the wire, sit
in the middle of it: listen on port 5200, forward to the real controller, and
decode everything passing through. Point NovaLCT at this machine instead of at
the processor and it will not notice.

Compared with packet capture it needs no elevated privileges, no libpcap, no
Wireshark, no promiscuous mode and no network tap -- and it recovers the stream
directly, so there is nothing to reassemble and nothing to lose to a truncated
snaplen. It also works when the vendor software runs on the same machine.

    python -m novasun proxy 192.168.1.40 --log session.jsonl

The log it writes is JSONL, one frame per line, and feeds straight into
:mod:`novasun.capture` for diffing and reporting.
"""

from __future__ import annotations

import json
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .capture import FrameEvent
from .names import NameIndex, default_index
from .protocol import Packet, ProtocolError
from .transport import TCP_PORT, FrameReader

Observer = Callable[[FrameEvent], None]


@dataclass
class ProxySession:
    """Records frames seen in both directions of one proxied connection."""

    events: list[FrameEvent] = field(default_factory=list)
    log_path: Path | None = None
    observers: list[Observer] = field(default_factory=list)
    _condition: threading.Condition = field(
        default_factory=threading.Condition, repr=False
    )

    def record(self, packet: Packet, raw: bytes, source: str, destination: str) -> None:
        event = FrameEvent(
            timestamp=time.time(), packet=packet, source=source, destination=destination
        )
        with self._condition:
            self.events.append(event)
            if self.log_path is not None:
                with self.log_path.open("a") as handle:
                    handle.write(
                        json.dumps(
                            {
                                "timestamp": event.timestamp,
                                "source": source,
                                "destination": destination,
                                "frame": raw.hex(),
                            }
                        )
                        + "\n"
                    )
            self._condition.notify_all()
        for observe in self.observers:
            observe(event)

    def wait_for(self, count: int, timeout: float = 2.0) -> bool:
        """Block until at least ``count`` frames have been recorded.

        Frames are recorded *after* being forwarded, so a client can complete a
        transaction fractionally before the proxy has finished observing it.
        Anything reading :attr:`events` right after driving the wire needs to
        wait, or it will race the last frame of the session.
        """
        with self._condition:
            return self._condition.wait_for(lambda: len(self.events) >= count, timeout)


class NovastarProxy:
    """Forwarding proxy for the register bus.

    One upstream connection per downstream connection. Bytes are forwarded
    immediately and decoded on the side, so a decode failure can never stall or
    corrupt the session being observed -- an important property when the thing
    on the other end is a live screen.
    """

    def __init__(
        self,
        target_host: str,
        target_port: int = TCP_PORT,
        listen_host: str = "0.0.0.0",
        listen_port: int = TCP_PORT,
        session: ProxySession | None = None,
    ) -> None:
        self.target = (target_host, target_port)
        self.session = session or ProxySession()
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((listen_host, listen_port))
        self._server.listen(4)
        self._running = False

    @property
    def address(self) -> tuple[str, int]:
        return self._server.getsockname()

    def serve_forever(self) -> None:
        self._running = True
        while self._running:
            try:
                client, peer = self._server.accept()
            except OSError:
                return
            threading.Thread(
                target=self._handle_client, args=(client, peer), daemon=True
            ).start()

    def serve_in_thread(self) -> threading.Thread:
        thread = threading.Thread(target=self.serve_forever, daemon=True)
        thread.start()
        return thread

    def shutdown(self) -> None:
        self._running = False
        try:
            self._server.close()
        except OSError:
            pass

    def _handle_client(self, client: socket.socket, peer: tuple[str, int]) -> None:
        client_name = f"{peer[0]}:{peer[1]}"
        target_name = f"{self.target[0]}:{self.target[1]}"
        try:
            upstream = socket.create_connection(self.target, timeout=10)
        except OSError:
            client.close()
            return
        client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        upstream.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        threads = [
            threading.Thread(
                target=self._pump,
                args=(client, upstream, client_name, target_name),
                daemon=True,
            ),
            threading.Thread(
                target=self._pump,
                args=(upstream, client, target_name, client_name),
                daemon=True,
            ),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        for endpoint in (client, upstream):
            try:
                endpoint.close()
            except OSError:
                pass

    def _pump(
        self, source: socket.socket, sink: socket.socket, source_name: str, sink_name: str
    ) -> None:
        reader = FrameReader()
        while True:
            try:
                chunk = source.recv(8192)
            except OSError:
                break
            if not chunk:
                break
            try:
                sink.sendall(chunk)
            except OSError:
                break
            # Decode after forwarding: observation must never delay the session.
            try:
                for packet in reader.feed(chunk):
                    self.session.record(
                        packet, packet.to_bytes(), source_name, sink_name
                    )
            except ProtocolError:
                reader = FrameReader()  # resynchronise and carry on
        try:
            sink.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def print_observer(names: NameIndex | None = None) -> Observer:
    """Observer that prints each decoded frame as it passes."""
    index = names or default_index()

    def observe(event: FrameEvent) -> None:
        print(event.describe(index), flush=True)

    return observe
