"""Command line front end -- a probe tool, and a worked example of the API.

    python -m novasun discover
    python -m novasun info 192.168.1.40
    python -m novasun status 192.168.1.40
    python -m novasun brightness 192.168.1.40 60
    python -m novasun test-pattern 192.168.1.40 red
    python -m novasun blackout 192.168.1.40 on
    python -m novasun read 192.168.1.40 0x02000001 1 --receiving-card

Reverse-engineering tools:

    python -m novasun proxy 192.168.1.40 --log session.jsonl
    python -m novasun capture decode session.jsonl
    python -m novasun capture diff before.pcapng after.pcapng
    python -m novasun capture report session.jsonl -o report.md
    python -m novasun coex snapshot 192.168.1.10 -o before.json

Options come after the positional arguments (``brightness HOST 60 --port
5200``); argparse cannot place an optional between two positionals.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import capture as capture_module
from . import coex as coex_module
from . import registers as reg
from .client import Controller
from .discovery import discover
from .names import DEFAULT_INDEX_PATH, NameIndex, import_address_mapping
from .protocol import Target, hexdump
from .proxy import NovastarProxy, ProxySession, print_observer
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


# --- capture analysis and proxying -----------------------------------------


def cmd_capture_decode(args: argparse.Namespace) -> int:
    events = capture_module.load(args.file)
    if not events:
        print("no register-bus frames found", file=sys.stderr)
        return 1
    names = NameIndex.load()
    for event in events:
        print(event.describe(names))
    print(f"\n{len(events)} frames", file=sys.stderr)
    return 0


def cmd_capture_report(args: argparse.Namespace) -> int:
    events = capture_module.load(args.file)
    text = capture_module.report(events, NameIndex.load())
    if args.output:
        Path(args.output).write_text(text)
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


def cmd_capture_diff(args: argparse.Namespace) -> int:
    before = capture_module.load(args.before)
    after = capture_module.load(args.after)
    differences = capture_module.diff(before, after)
    if not differences:
        print("no register writes differ between the two captures")
        return 0
    names = NameIndex.load()
    print(f"{len(differences)} register(s) differ:\n")
    for difference in differences:
        print("  " + difference.describe(names))
    return 0


def cmd_proxy(args: argparse.Namespace) -> int:
    log_path = Path(args.log) if args.log else None
    session = ProxySession(log_path=log_path)
    if not args.quiet:
        session.observers.append(print_observer(NameIndex.load()))
    proxy = NovastarProxy(
        target_host=args.target,
        target_port=args.target_port,
        listen_host=args.listen,
        listen_port=args.listen_port,
        session=session,
    )
    host, port = proxy.address
    print(
        f"proxying {host}:{port} -> {args.target}:{args.target_port}\n"
        f"point the vendor software at {host}:{port} and drive it; ctrl-c to stop",
        file=sys.stderr,
    )
    if log_path:
        print(f"logging frames to {log_path}", file=sys.stderr)
    try:
        proxy.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        proxy.shutdown()
    print(f"\n{len(session.events)} frames observed", file=sys.stderr)
    return 0


def cmd_names_import(args: argparse.Namespace) -> int:
    index = import_address_mapping(Path(args.source), Path(args.index))
    print(f"imported {len(index.imported)} names into {args.index}")
    print(f"{index.size} addresses known in total")
    return 0


def cmd_names_show(args: argparse.Namespace) -> int:
    index = NameIndex.load(Path(args.index))
    print(f"{len(index.builtin)} built-in, {len(index.imported)} imported")
    if args.address is not None:
        print(index.lookup(args.address) or "unknown")
    return 0


# --- COEX HTTP --------------------------------------------------------------


def cmd_coex_snapshot(args: argparse.Namespace) -> int:
    client = coex_module.CoexClient(args.host, args.port, timeout=args.timeout)
    data = coex_module.snapshot(client)
    text = json.dumps(data, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(text)
        print(f"wrote {args.output}")
    else:
        print(text)
    return 0


def cmd_coex_diff(args: argparse.Namespace) -> int:
    before = json.loads(Path(args.before).read_text())
    after = json.loads(Path(args.after).read_text())
    changes = coex_module.diff_snapshots(before, after)
    if not changes:
        print("snapshots are identical")
        return 0
    print(f"{len(changes)} field(s) changed:\n")
    for path, old, new in changes:
        print(f"  {path}\n      {old!r} -> {new!r}")
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

    # No literal '%' in help strings: argparse runs them through %-formatting.
    brightness = with_host("brightness", "set brightness, 0-100 percent")
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

    # capture analysis
    capture = sub.add_parser("capture", help="analyse captured traffic")
    capture_sub = capture.add_subparsers(dest="capture_command", required=True)

    decode = capture_sub.add_parser("decode", help="print every frame in a capture")
    decode.add_argument("file", help="pcap, pcapng, or a proxy .jsonl log")
    decode.set_defaults(func=cmd_capture_decode)

    report_cmd = capture_sub.add_parser("report", help="markdown summary by register")
    report_cmd.add_argument("file")
    report_cmd.add_argument("-o", "--output")
    report_cmd.set_defaults(func=cmd_capture_report)

    diff_cmd = capture_sub.add_parser(
        "diff", help="which registers two captures wrote differently"
    )
    diff_cmd.add_argument("before")
    diff_cmd.add_argument("after")
    diff_cmd.set_defaults(func=cmd_capture_diff)

    # proxy
    proxy = sub.add_parser("proxy", help="sit between vendor software and a controller")
    proxy.add_argument("target", help="the real controller's address")
    proxy.add_argument("--target-port", type=int, default=TCP_PORT)
    proxy.add_argument("--listen", default="0.0.0.0")
    proxy.add_argument("--listen-port", type=int, default=TCP_PORT)
    proxy.add_argument("--log", help="write a .jsonl session log")
    proxy.add_argument("--quiet", action="store_true", help="do not print frames")
    proxy.set_defaults(func=cmd_proxy)

    # address names
    names = sub.add_parser("names", help="manage the register name index")
    names_sub = names.add_subparsers(dest="names_command", required=True)

    names_import = names_sub.add_parser(
        "import", help="import an external address map (kept out of this repo)"
    )
    names_import.add_argument("source", help="path to an AddressMapping.ts")
    names_import.add_argument("--index", default=str(DEFAULT_INDEX_PATH))
    names_import.set_defaults(func=cmd_names_import)

    names_show = names_sub.add_parser("show", help="index size, or look one address up")
    names_show.add_argument("address", nargs="?", type=lambda v: int(v, 0))
    names_show.add_argument("--index", default=str(DEFAULT_INDEX_PATH))
    names_show.set_defaults(func=cmd_names_show)

    # COEX HTTP API
    coex = sub.add_parser("coex", help="the COEX HTTP API on port 8001")
    coex_sub = coex.add_subparsers(dest="coex_command", required=True)

    coex_snapshot = coex_sub.add_parser(
        "snapshot", help="dump every read-only endpoint to JSON"
    )
    coex_snapshot.add_argument("host")
    coex_snapshot.add_argument("--port", type=int, default=coex_module.DEFAULT_PORT)
    coex_snapshot.add_argument("-o", "--output")
    coex_snapshot.set_defaults(func=cmd_coex_snapshot)

    coex_diff = coex_sub.add_parser("diff", help="compare two snapshots")
    coex_diff.add_argument("before")
    coex_diff.add_argument("after")
    coex_diff.set_defaults(func=cmd_coex_diff)

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
