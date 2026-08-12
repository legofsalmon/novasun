# The NovaStar register bus

Reference for the protocol NovaLCT speaks to sending cards, receiving cards and
video processors, over RS232, USB-serial, TCP 5200 and UDP 5201. NovaStar's own
documents call it the "Nova Control System Protocol" (M3 document) and the
"Central Control Protocol" (COEX document); they describe the same thing.

Implementation: [`../src/novasun/protocol.py`](../src/novasun/protocol.py).
Conformance vectors: [`../tests/test_protocol.py`](../tests/test_protocol.py).

## Frame format

All multi-byte fields are little-endian.

| Offset | Size | Field | Notes |
|---|---|---|---|
| 0 | 2 | Header | `55 AA` request, `AA 55` response |
| 2 | 1 | ACK | `0` in requests; result code in responses |
| 3 | 1 | Serial number | Echoed by the response; do not reuse while in flight |
| 4 | 1 | Source address | `0xFE` = computer |
| 5 | 1 | Destination address | Sending-card position on the link, `0xFF` = broadcast |
| 6 | 1 | Device type | `0` sending card, `1` receiving card, `2` function card |
| 7 | 1 | Port address | RJ45 output port, `0xFF` = all ports |
| 8 | 2 | Board address | Receiving-card index on that port, `0xFFFF` = all |
| 10 | 1 | Code | `0` read, `1` write |
| 11 | 1 | Reserved | `0` |
| 12 | 4 | Register address | 32-bit |
| 16 | 2 | Data length | Bytes to read, or length of the payload written |
| 18 | N | Data | Present on write-requests and read-responses only |
| 18+N | 2 | Checksum | |

**Checksum.** `(sum of every byte after the header + 0x5555) & 0xFFFF`, stored
little-endian. A plain additive sum, despite being named CRC16 in some tooling.

**Frame length.** Not derivable from the length field alone. A write-request
carries its payload; its acknowledgement does not. A read-request is bare; its
response carries the data. So the total is
`20 + (length if (code == write) == (header == request) else 0)`, and a stream
reader needs the first 18 bytes before it can size the frame.

**Response codes** (ACK byte): `0` success, `1` timeout reaching the target
device, `2` checksum error in the request, `3` checksum error in the response,
`4` unknown command, `255` invalid.

## Addressing

Requests are routed hierarchically:

```
destination      which sending card on the serial chain / link  (0 for the only one)
  device_type    sending card, receiving card, or function card
    port         which RJ45 output on that sending card         (0xFF = all)
      rcv_index  which receiving card along that port           (0xFFFF = all)
```

NovaLCT's screen-wide commands use `destination=0xFF, port=0xFF,
rcv_index=0xFFFF` with `device_type=1`, which is why a brightness change is one
frame regardless of cabinet count. Per-cabinet commands set a real port and
index. Broadcast writes do not produce a meaningful acknowledgement — read a
single card back if you need confirmation.

## Register map

Confirmed registers, with provenance. `off` means "not engaged"; note that the
receiving-card display registers use `0xFF` rather than `0x01` for "on".

### Sending card / controller

| Address | Size | Meaning | Source |
|---|---|---|---|
| `0x00000002` | 2 | Controller model ID — the standard "are you there" probe | MCTRL 660 Pro doc |
| `0x00000004` | 2 | Communication protocol version | decompiled |
| `0x00000006` | 1 | `0xA8` marks a device that reports its max packet size | NovaLCT |
| `0x00000007` | 2 | Max packet size (else assume 256) | NovaLCT |
| `0x00000016` | 8 | Serial number / MAC | decompiled |
| `0x14000000` | 88 | Device name block: `0xA8` marker, length at +17, text at +18 | NovaLCT |
| `0x01000001` | 1 | **Save settings to flash** | M3 doc §3.15 |
| `0x01000002` | 1 | **Restore factory defaults** | M3 doc §3.4 |
| `0x02000023` | 1 | Input select — numbering is model-specific | MCTRL 660 Pro doc |
| `0x02100000` | 15+ | Screen configuration space | decompiled |
| `0x13010000` | 64 | Input signal state | decompiled |

### Receiving card (`device_type = 1`)

| Address | Size | Meaning | Source |
|---|---|---|---|
| `0x00000000` | 2 | Model ID — **non-zero means a card is present and working** | M3 doc §3.9 |
| `0x00000002` | 4 | Firmware version, e.g. `04 02 00 01` → 4.2.0.1 (all zeros = not running) | M3 doc §3.9 |
| `0x02000000` | 1 | Gamma value | decompiled |
| `0x02000001` | 1 | Global brightness, `0`–`0xFF` (ratio = value / `0xFF`) | COEX doc, M3 doc §3.3 |
| `0x02000001` | 5 | Global + R + G + B + virtual-R in one write | M3 doc §3.3 |
| `0x02000002` | 1..4 | Red / green / blue / virtual-red brightness | M3 doc §3.3 |
| `0x0200000F` | 2 | 16-bit brightness | decompiled |
| `0x02000023` | 1 | Input select (as above) | MCTRL 660 Pro doc |
| `0x02000074` | 1 | Low delay | decompiled |
| `0x02000100` | 1 | Blackout — `0x00` normal, `0xFF` blank ("kill mode") | COEX doc §3.2.3 |
| `0x02000101` | 1 | Test pattern — see table below | M3 doc §3.12.1 |
| `0x02000102` | 1 | Freeze — `0x00` running, `0xFF` frozen ("lock mode") | COEX doc §3.2.4 |
| `0x05000000` | 512 | Red gamma table (green at `+0x200`, blue at `+0x400`) | decompiled |
| `0x0A000000` | 256 | Monitoring block — temperature, humidity, voltage, fans, cables | M3 doc §3.1.1 |

**There is no receiving-card enumeration command.** The M3 document is explicit
about the method: "just try reading the receiving card model ID. If the ID can
be read back, it means the receiving card is working normally." So finding the
chain means walking `(port, index)` and reading two bytes at address 0 — a card
answers, an empty position returns `ack = TIMEOUT`.

That is one round trip per position, so walk until a couple of consecutive gaps
rather than probing all 64 addresses on all 16 ports.
`Controller.enumerate_receiving_cards` does this.

The model IDs live in a 0x41xx range (`0x4105` in the document's own example).
The mapping from ID to product name is **not documented anywhere available**,
and NovaLCT's decompiled table has only a generic `Scanner = 0x4101` entry, so
`ReceivingCard.name` reports the raw ID rather than guessing a product.

Test-pattern values: `0x00` normal, `0x02` red, `0x03` green, `0x04` blue,
`0x05` white, `0x06` horizontal line, `0x07` vertical line, `0x08` diagonal,
`0x09` grayscale ramp, `0x0A` aging loop.

Monitoring block leading fields: byte 0 temperature validity (bit 7 valid, bit 0
sign), byte 1 temperature in 0.5 °C units, byte 2 humidity (bit 7 valid, low 7
bits %RH), byte 3 supply voltage (bit 7 valid, low 7 bits in 0.1 V).

### Input selection is per model, register included

This is the single biggest per-model difference on the register bus, and it is
not just a matter of different values — **the register itself changes**. All
three maps below were transcribed from NovaStar protocol documents after
checksum-verifying every frame in them.

| Family | Register | Values |
|---|---|---|
| Sending cards (MCTRL660 Pro) | `0x02000023` | SDI `0x01`, HDMI `0x05`, DVI `0x58` |
| VX4S / VX4S-N | `0x0220002D` | DVI `0x10`, HDMI `0xA0`, VGA1 `0x01`, VGA2 `0x02`, CVBS1 `0x71`, CVBS2 `0x72`, SDI `0x40`, DP `0x90` |
| NovaPro HD | `0x02200022` | SDI `0x1A`, DVI `0x1C`, HDMI `0x1B`, VGA `0x17`, DP `0x1E`, CVBS `0x02` |
| COEX (MX/CX/KU) | HTTP | source IDs read from the controller at runtime |

"Switch to HDMI" is therefore `0x0220002D = 0xA0` on a VX4S, `0x02200022 = 0x1B`
on a NovaPro HD, and `0x02000023 = 0x05` on an MCTRL660 Pro. Three registers,
three values, one operation. Writing another model's byte to the wrong register
does nothing useful and may do something unintended.

The NovaPro UHD Jr has no published input-switching document. Its connectors are
known from the product specification — 1x DP 1.2, 4x DVI, 1x HDMI 2.0 with
loop-through, 2x 12G-SDI with loop, plus OPT inputs in fibre-converter mode and
a DVI mosaic composite source — but the select codes are not established, and
this repository refuses to switch rather than guessing at a live screen.

### Processor-level display control

The VX4S has its own display register, separate from the receiving-card kill and
lock registers, and **its value ordering is the opposite of the COEX API's**:

| | normal | freeze | blackout |
|---|---|---|---|
| VX4S `0x02200050` | `0` | `1` | `2` |
| COEX HTTP `displaymode` | `0` | `2` | `1` |

Send `1` meaning blackout to a VX4S and you freeze the screen; send `2` and you
black it out. That is the kind of difference worth encoding once, in data, which
is what `DisplayControl` on each device profile does.

The VX4S also exposes a front-panel lock at `0x022000F7` (`1` locks the LCD and
buttons, `0` releases them).

### COEX-generation controllers

| Address | Size | Meaning | Source |
|---|---|---|---|
| `0x0A000002` | 1 | Switch to preset *n* (1-based) | COEX doc §3.3 |
| `0x0A000003` | 3 | Layer source: layer, input card, connector | COEX doc §3.6 |
| `0x10000100` | 2 | Sending-card display: card number (`0xFF` all), then `0` normal / `1` blackout / `2` freeze | COEX doc §3.5 |
| `0x10000111` | 1 | Low latency on/off | COEX doc §3.4.2 |
| `0x10000116` | 1 | 3D on/off | COEX doc §3.4.4 |
| `0x10001118` | 1 | 3D eye: `0` right, `1` left | COEX doc §3.4.6 |
| `0x0008FFF2` | 1 | Working mode: `0` send-only, `1` all-in-one | COEX doc §3.4.8 |

A much larger map — roughly 1,500 named addresses — exists in the
`AddressMapping` enum generated from decompiled NovaLCT assemblies by the
`sarakusha/novastar` project. Read the provenance caveat in
[`investigation.md`](investigation.md#7-risks) before depending on it.

## Worked examples

Set brightness to 0 % on every receiving card:

```
55 aa 00 00 fe ff 01 ff ff ff 01 00 01 00 00 02 01 00 00 55 5a
```

Read the controller model ID (a read-request, so no payload):

```
55 AA 00 00 FE 00 00 00 00 00 00 00 02 00 00 00 02 00 57 56
AA 55 00 00 00 FE 00 00 00 00 00 00 02 00 00 00 02 00 07 11 6F 56   ← 0x1107
```

Blue test pattern on the first receiving card of port 0:

```
55 AA 00 80 FE 00 01 00 00 00 01 00 01 01 00 02 01 00 04 DE 56
AA 55 00 80 00 FE 01 00 00 00 01 00 01 01 00 02 00 00 D7 58
```

Recall preset 1 on a COEX controller:

```
55 aa 00 00 fe ff 01 ff ff ff 01 00 02 00 00 0a 01 00 01 5f 5a
```

Twenty-six such frames, drawn from four documents spanning 2014–2025, are
replayed against this codec by the test suite.

## Discovery

Send the ASCII bytes `rqProMI:` from UDP port 3800 to the subnet broadcast
address and to the multicast group `224.224.125.119`, both on port 3800.
Controllers reply with `rpProMI:` plus device detail; the reply's source address
is the controller. Bind the *source* port to 3800 as well — some firmware
replies to the port it was contacted from.

## Implementation notes

- Serial numbers wrap at 256. Match responses by serial number and discard
  stale ones rather than pairing whatever arrives next with the current request.
- Chunk transfers at the device's advertised maximum packet size, or 256 bytes
  when it does not advertise one. Split by adding the offset to the register
  address.
- Enumerate the chain by probing model ID at ascending destination indices and
  stopping after two consecutive non-answers.
- On serial links, remember the two baud rates: 115200 for MSD300/MCTRL300/500
  and COEX central control, 1048576 for MSD600/MCTRL600/660.
