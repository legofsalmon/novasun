"""Command line front end -- a probe tool, and a worked example of the API.

    python -m novasun discover
    python -m novasun info 192.168.1.40
    python -m novasun status 192.168.1.40
    python -m novasun brightness 192.168.1.40 60
    python -m novasun test-pattern 192.168.1.40 red
    python -m novasun blackout 192.168.1.40 on
    python -m novasun read 192.168.1.40 0x02000001 1 --receiving-card

Options come after the positional arguments (``brightness HOST 60 --port
5200``); argparse cannot place an optional between two positionals.
"""

from __future__ import annotations

import argparse
import sys

from . import registers as reg
from .client import Controller
from .discovery import discover
from .protocol import Target, hexdump
from .transport import TCP_PORT


def _controller(args: argparse.Namespace) -> Controller:
    return Controller.connect(args.host, args.port, timeout=args.timeout)


def cmd_discover(args: argparse.Namespace) -> int:
    devices = discover(timeout=args.timeout)
    if not devices:
        print("no controllers answered the discovery probe")
        return 1
    for device in devices:
        print(f"{device.address}\t{device.detail}")
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    with _controller(args) as controller:
        devices = controller.enumerate_devices()
        if not devices:
            print("connected, but no device answered a model-id read")
            return 1
        for index, info in enumerate(devices):
            print(f"device {index}")
            print(f"  model id        0x{info.model_id:04x}")
            print(f"  serial          {info.serial}")
            print(f"  name            {info.name or '(unnamed)'}")
            print(f"  max packet size {info.max_packet_size}")
    return 0


def cmd_brightness(args: argparse.Namespace) -> int:
    with _controller(args) as controller:
        controller.set_brightness(args.percent)
    print(f"brightness set to {args.percent:g} %")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """Read back the display state of one receiving card."""
    card = Target.receiving_card(port=args.port_index, index=args.card_index)
    with _controller(args) as controller:
        brightness = controller.read(reg.GLOBAL_BRIGHTNESS, 1, card)[0]
        blackout = controller.read(reg.KILL_MODE, 1, card)[0]
        frozen = controller.read(reg.LOCK_MODE, 1, card)[0]
        pattern = controller.read(reg.SELF_TEST_MODE, 1, card)[0]
    print(f"brightness   {brightness} / 255  ({brightness * 100 / 255:.1f} %)")
    print(f"blackout     {'on' if blackout else 'off'}")
    print(f"freeze       {'on' if frozen else 'off'}")
    try:
        pattern_name = reg.TestPattern(pattern).name.lower()
    except ValueError:
        pattern_name = f"unknown (0x{pattern:02x})"
    print(f"test pattern {pattern_name}")
    return 0


def cmd_blackout(args: argparse.Namespace) -> int:
    with _controller(args) as controller:
        controller.blackout(args.state == "on")
    print(f"blackout {args.state}")
    return 0


def cmd_freeze(args: argparse.Namespace) -> int:
    with _controller(args) as controller:
        controller.freeze(args.state == "on")
    print(f"freeze {args.state}")
    return 0


def cmd_test_pattern(args: argparse.Namespace) -> int:
    pattern = reg.TestPattern[args.pattern.upper().replace("-", "_")]
    with _controller(args) as controller:
        controller.set_test_pattern(pattern)
    print(f"test pattern: {pattern.name.lower()}")
    return 0


def cmd_read(args: argparse.Namespace) -> int:
    target = Target.all_receiving_cards() if args.receiving_card else Target.sending_card()
    with _controller(args) as controller:
        data = controller.read(args.address, args.length, target)
    print(hexdump(data))
    return 0


def cmd_write(args: argparse.Namespace) -> int:
    payload = bytes.fromhex(args.data.replace(" ", ""))
    target = Target.all_receiving_cards() if args.receiving_card else Target.sending_card()
    with _controller(args) as controller:
        controller.write(args.address, payload, target)
    print(f"wrote {len(payload)} byte(s) to 0x{args.address:08x}")
    return 0


def cmd_monitor(args: argparse.Namespace) -> int:
    with _controller(args) as controller:
        status = controller.read_receiver_monitoring(args.port_index, args.card_index)
    print(f"temperature {status.temperature_c} C")
    print(f"humidity    {status.humidity_percent} %RH")
    print(f"voltage     {status.voltage_v} V")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="novasun", description=__doc__.splitlines()[0])
    parser.add_argument("--timeout", type=float, default=2.0)
    sub = parser.add_subparsers(dest="command", required=True)

    discover_parser = sub.add_parser("discover", help="broadcast for controllers")
    discover_parser.set_defaults(func=cmd_discover)

    def with_host(name: str, help_text: str):
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("host")
        sp.add_argument("--port", type=int, default=TCP_PORT)
        return sp

    with_host("info", "identify the connected device(s)").set_defaults(func=cmd_info)

    brightness = with_host("brightness", "set brightness, 0-100 %")
    brightness.add_argument("percent", type=float)
    brightness.set_defaults(func=cmd_brightness)

    status = with_host("status", "read back one receiving card's display state")
    status.add_argument("--port-index", type=int, default=0)
    status.add_argument("--card-index", type=int, default=0)
    status.set_defaults(func=cmd_status)

    blackout = with_host("blackout", "blank the receiving cards")
    blackout.add_argument("state", choices=["on", "off"])
    blackout.set_defaults(func=cmd_blackout)

    freeze = with_host("freeze", "freeze the receiving cards")
    freeze.add_argument("state", choices=["on", "off"])
    freeze.set_defaults(func=cmd_freeze)

    pattern = with_host("test-pattern", "show a built-in test pattern")
    pattern.add_argument(
        "pattern", choices=[p.name.lower() for p in reg.TestPattern]
    )
    pattern.set_defaults(func=cmd_test_pattern)

    read = with_host("read", "read raw registers")
    read.add_argument("address", type=lambda v: int(v, 0))
    read.add_argument("length", type=lambda v: int(v, 0))
    read.add_argument("--receiving-card", action="store_true")
    read.set_defaults(func=cmd_read)

    write = with_host("write", "write raw registers (hex payload)")
    write.add_argument("address", type=lambda v: int(v, 0))
    write.add_argument("data")
    write.add_argument("--receiving-card", action="store_true")
    write.set_defaults(func=cmd_write)

    monitor = with_host("monitor", "read a receiving card's monitoring block")
    monitor.add_argument("--port-index", type=int, default=0)
    monitor.add_argument("--card-index", type=int, default=0)
    monitor.set_defaults(func=cmd_monitor)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
