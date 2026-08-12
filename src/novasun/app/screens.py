"""Screens: the unit an operator actually thinks in.

Nobody running a show thinks "192.168.1.40, output port 3". They think "the main
wall". A screen and a processor are not the same thing and do not map one to
one: a wall can span two processors, and one processor can drive several
screens off different ports.

So a screen is a named set of *parts of devices*:

* on the register bus, a member names the output **ports** it occupies -- ports
  0 and 1 of this processor, port 0 of that one;
* on COEX hardware, a member names the controller's own **screen IDs**, because
  the controller already has a model of the installation and inventing a second
  one on top would just disagree with VMP.

A member with neither is the whole device, which is the common single-processor
case and keeps simple setups simple.

None of this is discoverable. Which ports feed which wall is knowledge about a
venue, not about a protocol, so it is entered by a human and persisted -- see
:mod:`novasun.app.config`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    return _SLUG.sub("-", name.strip().lower()).strip("-") or "screen"


@dataclass
class ScreenMember:
    """One device's contribution to a screen."""

    address: str
    ports: list[int] | None = None
    """Register-bus output ports. ``None`` means the whole device."""
    screen_ids: list[str] | None = None
    """COEX controller screen IDs. ``None`` means the whole device."""
    note: str = ""

    @property
    def whole_device(self) -> bool:
        return not self.ports and not self.screen_ids

    def describe(self) -> str:
        if self.ports:
            return f"{self.address} ports {', '.join(str(p) for p in self.ports)}"
        if self.screen_ids:
            return f"{self.address} screens {', '.join(self.screen_ids)}"
        return f"{self.address} (whole device)"

    def to_dict(self) -> dict[str, Any]:
        return {
            "address": self.address,
            "ports": self.ports,
            "screen_ids": self.screen_ids,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ScreenMember":
        ports = raw.get("ports")
        screen_ids = raw.get("screen_ids")
        return cls(
            address=str(raw["address"]),
            ports=[int(p) for p in ports] if ports else None,
            screen_ids=[str(s) for s in screen_ids] if screen_ids else None,
            note=str(raw.get("note") or ""),
        )


@dataclass
class Screen:
    """A named display surface, made of parts of one or more processors."""

    identifier: str
    name: str
    members: list[ScreenMember] = field(default_factory=list)
    note: str = ""

    @classmethod
    def create(cls, name: str, members: list[ScreenMember] | None = None) -> "Screen":
        return cls(identifier=slugify(name), name=name, members=members or [])

    @property
    def addresses(self) -> list[str]:
        seen: list[str] = []
        for member in self.members:
            if member.address not in seen:
                seen.append(member.address)
        return seen

    def member_for(self, address: str) -> ScreenMember | None:
        for member in self.members:
            if member.address == address:
                return member
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "name": self.name,
            "note": self.note,
            "members": [member.to_dict() for member in self.members],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Screen":
        return cls(
            identifier=str(raw.get("identifier") or slugify(str(raw.get("name", "")))),
            name=str(raw.get("name") or raw.get("identifier") or "Screen"),
            note=str(raw.get("note") or ""),
            members=[ScreenMember.from_dict(m) for m in raw.get("members", [])],
        )


@dataclass
class ScreenState:
    """A screen's aggregate condition, for rendering.

    Aggregation is deliberately pessimistic: a screen is only ``online`` when
    every member is. Half a wall being reachable is not a healthy screen, and
    reporting it as one is how an operator gets surprised.
    """

    identifier: str
    name: str
    note: str = ""
    members: list[dict[str, Any]] = field(default_factory=list)
    reachability: str = "unknown"
    device_count: int = 0
    online_count: int = 0
    cabinets_total: int = 0
    cabinets_online: int = 0
    hottest_c: float | None = None
    problems: list[str] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return (
            self.reachability == "online"
            and not self.problems
            and (self.cabinets_total == 0 or self.cabinets_online == self.cabinets_total)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "identifier": self.identifier,
            "name": self.name,
            "note": self.note,
            "members": self.members,
            "reachability": self.reachability,
            "device_count": self.device_count,
            "online_count": self.online_count,
            "cabinets_total": self.cabinets_total,
            "cabinets_online": self.cabinets_online,
            "hottest_c": self.hottest_c,
            "problems": self.problems,
            "healthy": self.healthy,
        }


def aggregate(screen: Screen, device_states: dict[str, Any]) -> ScreenState:
    """Roll member device states up into one screen state."""
    state = ScreenState(
        identifier=screen.identifier,
        name=screen.name,
        note=screen.note,
        members=[member.to_dict() for member in screen.members],
        device_count=len(screen.addresses),
    )

    reachabilities: list[str] = []
    temperatures: list[float] = []
    for address in screen.addresses:
        device = device_states.get(address)
        if device is None:
            state.problems.append(f"{address} is not in the device list")
            reachabilities.append("unknown")
            continue
        reachability = device.get("reachability", "unknown")
        reachabilities.append(reachability)
        if reachability == "online":
            state.online_count += 1
        else:
            state.problems.append(f"{address} is {reachability}")

        status = device.get("status") or {}
        total = status.get("cabinets_total")
        if total:
            state.cabinets_total += int(total)
            state.cabinets_online += int(status.get("cabinets_online") or 0)
        temperature = status.get("temperature_c")
        if isinstance(temperature, (int, float)):
            temperatures.append(float(temperature))

        cards = device.get("receiving_cards") or []
        unhealthy = [card for card in cards if not card.get("healthy")]
        if unhealthy:
            state.problems.append(
                f"{address}: {len(unhealthy)} receiving card(s) not running"
            )

    if temperatures:
        state.hottest_c = max(temperatures)

    if not reachabilities or all(value == "unknown" for value in reachabilities):
        # Nothing was tried -- an empty screen, or one naming devices the
        # application does not hold. "unreachable" would claim a failed attempt
        # and point the operator at the network instead of at the config.
        state.reachability = "unknown"
    elif all(value == "online" for value in reachabilities):
        state.reachability = "online"
    elif any(value == "online" for value in reachabilities):
        state.reachability = "partial"
    elif "in-use" in reachabilities:
        state.reachability = "in-use"
    else:
        state.reachability = "unreachable"

    if state.cabinets_total and state.cabinets_online < state.cabinets_total:
        state.problems.append(
            f"{state.cabinets_total - state.cabinets_online} cabinet(s) offline"
        )
    return state
