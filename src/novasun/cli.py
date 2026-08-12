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
from . import devices
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
    found = discover(timeout=args.timeout)
    if not found:
        print("no controllers answered the discovery probe")
        return 1
    for device in found:
        print(f"{device.address}\t{device.detail}")
    return 0


def cmd_identify(args: argparse.Namespace) -> int:
    """Work out what a device is and which control path applies."""
    identification = devices.identify(args.host, timeout=args.timeout)
    if not (identification.reachable_http or identification.reachable_register_bus):
        print(f"nothing answered at {args.host}", file=sys.stderr)
        return 1
    print(identification.summary())
    return 0


def cmd_inputs(args: argparse.Namespace) -> int:
    """List a device's inputs, and whether each can actually be switched to."""
    from .processor import Processor

    with Processor.connect(args.host, timeout=args.timeout) as processor:
        states = processor.inputs()
        if not states:
            print(f"{processor.profile.name} reports no switchable inputs")
            return 0
        print(f"{processor.profile.name}")
        for state in states:
            mark = " " if state.switchable else "*"
            connected = ""
            if state.connected is not None:
                connected = "  [signal]" if state.connected else "  [no signal]"
            note = f"  -- {state.notes}" if state.notes else ""
            print(f" {mark} {state.label:<14} {state.type:<12}{connected}{note}")
        if any(not state.switchable for state in states):
            print("\n * select code not established for this model; see "
                  "docs/capture-workflow.md")
    return 0


def cmd_select_input(args: argparse.Namespace) -> int:
    from .processor import CapabilityUnknown, NotSupported, Processor

    try:
        with Processor.connect(args.host, timeout=args.timeout) as processor:
            processor.select_input(args.input)
    except (CapabilityUnknown, NotSupported) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"input switched to {args.input}")
    return 0


def cmd_outputs(args: argparse.Namespace) -> int:
    from .processor import Processor

    with Processor.connect(args.host, timeout=args.timeout) as processor:
        detail = processor.outputs()
        print(f"{processor.profile.name}")
        print(f"  ethernet ports {detail['ethernet_ports']}")
        if detail["fibre_ports"]:
            print(f"  fibre ports    {detail['fibre_ports']}")
        for output in detail["other"]:
            suffix = " (loop-through)" if output["loop_through"] else ""
            print(f"  {output['count']}x {output['label']}{suffix}")
    return 0


def cmd_survey(args: argparse.Namespace) -> int:
    """Read-only survey of the processors on this network."""
    from .survey import survey_network

    result = survey_network(
        hosts=args.host or None,
        timeout=args.timeout,
        allow_probe=not args.no_probe,
        allow_register_bus=args.register_bus,
    )
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(result.summary())
    return 0 if result.reachable else 1


def cmd_listen(args: argparse.Namespace) -> int:
    """Observe discovery traffic without transmitting anything."""
    from .passive import PassiveListener, build_inventory

    log_path = Path(args.log) if args.log else None
    listener = PassiveListener(log_path=log_path)
    host, port = listener.address
    print(
        f"listening on {host}:{port}, transmitting nothing "
        f"({'until ctrl-c' if args.duration is None else f'for {args.duration:g}s'})",
        file=sys.stderr,
    )
    if not args.quiet:
        listener.observers.append(lambda o: print(o.describe(), flush=True))
    try:
        listener.listen(args.duration)
    except KeyboardInterrupt:
        pass
    finally:
        listener.stop()
    print()
    print(build_inventory(listener.observations).summary())
    return 0


def cmd_watch(args: argparse.Namespace) -> int:
    """Poll a COEX controller read-only and print status."""
    import time as _time

    from .monitor import CoexMonitor

    with CoexMonitor(args.host, args.port, timeout=args.timeout) as monitor:
        while True:
            snapshot = monitor.poll()
            print(snapshot.summary(), flush=True)
            if args.once:
                return 0
            print("-" * 40)
            try:
                _time.sleep(args.interval)
            except KeyboardInterrupt:
                return 0


def cmd_models(args: argparse.Namespace) -> int:
    rows = sorted(devices.MODELS.values(), key=lambda p: (p.family.value, p.name))
    rows += sorted(set(devices.COEX_MODELS.values()), key=lambda p: p.name)
    print(f"{'model':<18} {'id':<8} {'eth':>4} {'fibre':>6}  {'inputs':<28} control")
    for profile in rows:
        identifier = f"0x{profile.model_id:04x}" if profile.model_id else "-"
        control = "http 8001" if profile.http_api else f"tcp {profile.control_port}"
        if profile.http_api:
            inputs = "(read from controller)"
        elif profile.inputs:
            known = len(profile.switchable_inputs)
            inputs = f"{len(profile.inputs)} ({known} switchable)"
        else:
            inputs = "-"
        print(
            f"{profile.name:<18} {identifier:<8} {profile.port_count:>4} "
            f"{profile.fibre_ports or '':>6}  {inputs:<28} {control}"
        )
    return 0


def cmd_simulate(args: argparse.Namespace) -> int:
    if args.kind == "coex":
        from .coexsim import CoexState, SimulatedCoexController

        model = args.model or "MX40 Pro"
        server = SimulatedCoexController(
            args.host,
            args.port if args.port is not None else 8001,
            CoexState(model=model),
        )
        host, port = server.address
        print(f"simulating {server.state.model} HTTP API on http://{host}:{port}")
    else:
        from .simulator import MODEL_ALIASES, SimulatedController

        model = args.model or "vx4s"
        model_id = MODEL_ALIASES.get(model.lower())
        if model_id is None:
            try:
                model_id = int(model, 0)
            except ValueError:
                print(
                    f"unknown model {model!r}; try one of: "
                    + ", ".join(sorted(MODEL_ALIASES)),
                    file=sys.stderr,
                )
                return 2
        server = SimulatedController(
            args.host,
            args.port if args.port is not None else TCP_PORT,
            model_id=model_id,
            cards_per_port=args.cards_per_port,
            latency=args.latency,
        )
        host, port = server.address
        print(
            f"simulating {server.profile.name} on {host}:{port} -- "
            f"{server.port_count} ports x {server.cards_per_port} receiving cards"
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    with _controller(args) as controller:
        chain = controller.enumerate_devices()
        if not chain:
            print("connected, but no device answered a model-id read")
            return 1
        for index, info in enumerate(chain):
            profile = devices.profile_for(info.model_id)
            print(f"device {index}")
            print(f"  model           {profile.name}")
            print(f"  model id        0x{info.model_id:04x}")
            print(f"  output ports    {profile.port_count}")
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

    identify_parser = sub.add_parser(
        "identify", help="what is this device, and how should it be driven"
    )
    identify_parser.add_argument("host")
    identify_parser.set_defaults(func=cmd_identify)

    models = sub.add_parser("models", help="list known models and their capabilities")
    models.set_defaults(func=cmd_models)

    simulate = sub.add_parser("simulate", help="run a fake controller for development")
    simulate.add_argument(
        "kind", choices=["register", "coex"], help="register bus, or the COEX HTTP API"
    )
    simulate.add_argument("--host", default="127.0.0.1")
    simulate.add_argument("--port", type=int, help="default 5200, or 8001 for coex")
    simulate.add_argument(
        "--model",
        help="register bus: an alias or hex id (default vx4s); coex: a model name "
        "(default MX40 Pro)",
    )
    simulate.add_argument("--cards-per-port", type=int, default=2)
    simulate.add_argument("--latency", type=float, default=0.0)
    simulate.set_defaults(func=cmd_simulate)

    survey_parser = sub.add_parser(
        "survey", help="read-only survey of the processors on this network"
    )
    survey_parser.add_argument("host", nargs="*", help="addresses to include")
    survey_parser.add_argument(
        "--no-probe", action="store_true", help="do not broadcast; use given hosts only"
    )
    survey_parser.add_argument(
        "--register-bus",
        action="store_true",
        help="fall back to a control session on non-COEX models (not read-only-safe)",
    )
    survey_parser.add_argument("--json", action="store_true")
    survey_parser.set_defaults(func=cmd_survey)

    listen_parser = sub.add_parser(
        "listen", help="observe discovery traffic, transmitting nothing"
    )
    listen_parser.add_argument("--duration", type=float, help="seconds; default forever")
    listen_parser.add_argument("--log", help="append raw datagrams to a file")
    listen_parser.add_argument("--quiet", action="store_true")
    listen_parser.set_defaults(func=cmd_listen)

    watch = sub.add_parser("watch", help="read-only status polling of a COEX controller")
    watch.add_argument("host")
    watch.add_argument("--port", type=int, default=coex_module.DEFAULT_PORT)
    watch.add_argument("--interval", type=float, default=15.0)
    watch.add_argument("--once", action="store_true")
    watch.set_defaults(func=cmd_watch)

    inputs_parser = sub.add_parser("inputs", help="list a device's inputs")
    inputs_parser.add_argument("host")
    inputs_parser.set_defaults(func=cmd_inputs)

    select = sub.add_parser("select-input", help="switch input by label")
    select.add_argument("host")
    select.add_argument("input", help='e.g. "HDMI", "VGA 2", "12G-SDI"')
    select.set_defaults(func=cmd_select_input)

    outputs_parser = sub.add_parser("outputs", help="list a device's outputs")
    outputs_parser.add_argument("host")
    outputs_parser.set_defaults(func=cmd_outputs)

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
