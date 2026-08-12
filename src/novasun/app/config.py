"""On-disk configuration: the things that cannot be discovered.

A processor's model, port count and inputs are read from the hardware. Which
wall its ports feed, and what that wall is called, are facts about a venue that
no probe can recover. Those have to be written down, and they have to survive a
restart, or the application is only useful for as long as one process stays up.

The file is JSON at ``~/.novasun/config.json``, written atomically -- to a
temporary file in the same directory, then renamed -- so an interrupted save
cannot leave a half-written config where a working one used to be.

A config that fails to parse is **moved aside rather than overwritten**. Losing
a venue's screen layout to a stray character would be worse than starting empty,
and the broken file is often repairable by hand.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .screens import Screen

CONFIG_VERSION = 1
DEFAULT_DIRECTORY = Path.home() / ".novasun"
DEFAULT_PATH = DEFAULT_DIRECTORY / "config.json"


@dataclass
class DeviceEntry:
    """A device the application should know about at startup."""

    address: str
    label: str = ""
    """Operator's name for it. The device also reports one; this wins."""
    ports: dict[str, int] = field(default_factory=dict)
    """Non-standard control/HTTP ports, if any."""

    def to_dict(self) -> dict[str, Any]:
        entry: dict[str, Any] = {"address": self.address}
        if self.label:
            entry["label"] = self.label
        if self.ports:
            entry["ports"] = self.ports
        return entry

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DeviceEntry":
        return cls(
            address=str(raw["address"]),
            label=str(raw.get("label") or ""),
            ports={k: int(v) for k, v in (raw.get("ports") or {}).items()},
        )


@dataclass
class Config:
    """Everything the application remembers between runs."""

    version: int = CONFIG_VERSION
    devices: list[DeviceEntry] = field(default_factory=list)
    screens: list[Screen] = field(default_factory=list)
    refresh_interval: float = 10.0
    path: Path | None = None
    load_error: str | None = None
    """Set when the file on disk could not be read; the app surfaces it."""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": CONFIG_VERSION,
            "refresh_interval": self.refresh_interval,
            "devices": [device.to_dict() for device in self.devices],
            "screens": [screen.to_dict() for screen in self.screens],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any], path: Path | None = None) -> "Config":
        version = int(raw.get("version") or CONFIG_VERSION)
        if version > CONFIG_VERSION:
            raise ConfigError(
                f"config version {version} is newer than this build understands "
                f"({CONFIG_VERSION}); upgrade novasun rather than letting it "
                "rewrite the file"
            )
        return cls(
            version=version,
            refresh_interval=float(raw.get("refresh_interval") or 10.0),
            devices=[DeviceEntry.from_dict(d) for d in raw.get("devices", [])],
            screens=[Screen.from_dict(s) for s in raw.get("screens", [])],
            path=path,
        )

    def save(self, path: Path | None = None) -> Path:
        """Write atomically: temp file in the same directory, then rename."""
        destination = Path(path or self.path or DEFAULT_PATH)
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + f".tmp{os.getpid()}")
        temporary.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        temporary.replace(destination)
        self.path = destination
        return destination


class ConfigError(Exception):
    pass


def load(path: Path | None = None) -> Config:
    """Read the config, or return an empty one.

    A missing file is normal on first run. A *corrupt* file is moved aside with
    a timestamp so the operator can recover it, and an empty config is returned
    rather than refusing to start -- an application that will not launch during
    a show is worse than one that has forgotten its screens.
    """
    destination = Path(path or DEFAULT_PATH)
    if not destination.exists():
        return Config(path=destination)
    try:
        raw = json.loads(destination.read_text())
        if not isinstance(raw, dict):
            raise ValueError("config root is not an object")
        return Config.from_dict(raw, path=destination)
    except ConfigError:
        raise
    except (OSError, ValueError, KeyError) as exc:
        salvaged = destination.with_suffix(f".broken-{int(time.time())}.json")
        try:
            destination.rename(salvaged)
        except OSError:
            salvaged = destination
        return Config(
            path=destination,
            load_error=f"{exc}; previous config kept at {salvaged}",
        )
