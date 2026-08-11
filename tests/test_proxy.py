"""The proxy under test against the simulator: a full observe-and-analyse loop."""

from __future__ import annotations

import pytest

from novasun import capture, registers as reg
from novasun.client import Controller
from novasun.protocol import IO
from novasun.proxy import NovastarProxy, ProxySession
from novasun.simulator import SimulatedController


@pytest.fixture()
def device():
    server = SimulatedController("127.0.0.1", 0)
    server.serve_in_thread()
    yield server
    server.shutdown()
    server.server_close()


@pytest.fixture()
def proxied(device, tmp_path):
    """A proxy in front of the simulator, logging to a session file."""
    session = ProxySession(log_path=tmp_path / "session.jsonl")
    host, port = device.address
    proxy = NovastarProxy(
        target_host=host,
        target_port=port,
        listen_host="127.0.0.1",
        listen_port=0,
        session=session,
    )
    proxy.serve_in_thread()
    yield proxy, session, device
    proxy.shutdown()


def test_proxy_forwards_transparently(proxied) -> None:
    """The client must not be able to tell it is talking through the proxy."""
    proxy, _session, device = proxied
    host, port = proxy.address
    with Controller.connect(host, port, timeout=2.0) as controller:
        info = controller.probe()
        assert info is not None and info.model_id == 0x1107

        controller.set_brightness(60)
        assert device.registers.read(reg.GLOBAL_BRIGHTNESS, 1) == bytes(
            [reg.brightness_byte(60)]
        )


def test_proxy_observes_both_directions(proxied) -> None:
    proxy, session, _device = proxied
    host, port = proxy.address
    with Controller.connect(host, port, timeout=2.0) as controller:
        controller.set_brightness(60)
    assert session.wait_for(2), "proxy did not observe both directions"

    requests = [e for e in session.events if not e.packet.is_response]
    responses = [e for e in session.events if e.packet.is_response]
    assert requests and responses
    write = next(e for e in requests if e.packet.io == IO.WRITE)
    assert write.packet.address == reg.GLOBAL_BRIGHTNESS
    assert write.packet.data == bytes([reg.brightness_byte(60)])


def test_session_log_feeds_the_capture_analyser(proxied, tmp_path) -> None:
    """Proxy output and pcap input converge on the same analysis."""
    proxy, session, _device = proxied
    host, port = proxy.address
    with Controller.connect(host, port, timeout=2.0) as controller:
        controller.set_brightness(60)
        controller.set_test_pattern(reg.TestPattern.WHITE)
    assert session.wait_for(4), "proxy did not observe the whole session"

    events = capture.load(session.log_path)
    summary = capture.summarise(events)
    assert summary[reg.GLOBAL_BRIGHTNESS].final_write == bytes([reg.brightness_byte(60)])
    assert summary[reg.SELF_TEST_MODE].final_write == bytes([reg.TestPattern.WHITE])

    text = capture.report(events)
    assert "GLOBAL_BRIGHTNESS" in text and "SELF_TEST_MODE" in text


def test_diffing_two_proxied_runs_isolates_the_changed_register(device, tmp_path) -> None:
    """The workflow end to end: run twice, change one thing, diff."""

    def run(name: str, percent: float):
        session = ProxySession(log_path=tmp_path / name)
        host, port = device.address
        proxy = NovastarProxy(
            target_host=host,
            target_port=port,
            listen_host="127.0.0.1",
            listen_port=0,
            session=session,
        )
        proxy.serve_in_thread()
        try:
            proxy_host, proxy_port = proxy.address
            with Controller.connect(proxy_host, proxy_port, timeout=2.0) as controller:
                controller.probe()
                controller.set_brightness(percent)
            session.wait_for(2)
        finally:
            proxy.shutdown()
        return capture.load(session.log_path)

    differences = capture.diff(run("a.jsonl", 30), run("b.jsonl", 90))
    assert len(differences) == 1
    assert differences[0].address == reg.GLOBAL_BRIGHTNESS
    assert differences[0].before == bytes([reg.brightness_byte(30)])
    assert differences[0].after == bytes([reg.brightness_byte(90)])
