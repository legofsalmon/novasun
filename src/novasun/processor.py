"""One interface over both control paths, aware of what each model can do.

``Processor`` binds a connection to its :class:`~novasun.devices.DeviceProfile`
and exposes operations in the application's terms -- "switch to HDMI", "freeze"
-- resolving them to whatever that particular model needs. A VX4S gets
``0x0220002D = 0xA0``; a NovaPro HD gets ``0x02200022 = 0x1B``; an MX40 Pro gets
an HTTP PUT with a source ID read from the controller.

The important property is that it **refuses rather than guesses**. Where a
connector exists but its select code has not been established -- every input on
the NovaPro UHD Jr, for instance -- switching to it raises
:class:`CapabilityUnknown` instead of writing a plausible byte to a live screen.
Ask :meth:`Processor.inputs` what is switchable before offering it in a UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import registers as reg
from .client import Controller, ReceiverStatus
from .coex import CoexClient
from .devices import (
    ConnectorType,
    DeviceProfile,
    Family,
    Identification,
    InputConnector,
    identify,
)
from .protocol import Target

DisplayMode = reg.DisplayMode


class CapabilityUnknown(Exception):
    """The model has this feature, but how to drive it has not been established.

    Distinct from "not supported": this is a gap in our knowledge of the device,
    not a limit of the device. It is raised in preference to writing a guessed
    value.
    """


class NotSupported(Exception):
    """The model genuinely does not have this capability."""


@dataclass
class InputState:
    """An input as presented to the application."""

    label: str
    type: str
    switchable: bool
    identifier: int | str | None = None
    connected: bool | None = None
    notes: str = ""


class Processor:
    """A connected NovaStar processor, driven through whichever path it speaks."""

    def __init__(
        self,
        profile: DeviceProfile,
        controller: Controller | None = None,
        coex: CoexClient | None = None,
        identification: Identification | None = None,
    ) -> None:
        if controller is None and coex is None:
            raise ValueError("a Processor needs a register-bus or an HTTP connection")
        self.profile = profile
        self.controller = controller
        self.coex = coex
        self.identification = identification

    # --- construction -------------------------------------------------------

    @classmethod
    def connect(cls, host: str, timeout: float = 2.0, **ports: int) -> "Processor":
        """Identify what is at ``host`` and open the right connection to it."""
        identification = identify(host, timeout=timeout, **ports)
        if not (identification.reachable_http or identification.reachable_register_bus):
            raise ConnectionError(f"nothing answered at {host}")

        coex = None
        controller = None
        if identification.reachable_http and identification.profile.http_api:
            coex = CoexClient(host, identification.http_port, timeout=timeout)
        if identification.reachable_register_bus:
            controller = Controller.connect(
                host, identification.register_bus_port, timeout=timeout
            )
        return cls(identification.profile, controller, coex, identification)

    def close(self) -> None:
        if self.controller is not None:
            self.controller.close()

    def __enter__(self) -> "Processor":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def uses_http(self) -> bool:
        return self.coex is not None

    def _require_controller(self, what: str) -> Controller:
        if self.controller is None:
            raise NotSupported(f"{what} needs a register-bus connection")
        return self.controller

    # --- inputs -------------------------------------------------------------

    def inputs(self) -> list[InputState]:
        """The model's inputs.

        COEX controllers are asked; everything else is answered from the
        profile, because the register bus has no way to enumerate.
        """
        if self.coex is not None:
            return self._coex_inputs()
        return [
            InputState(
                label=connector.label,
                type=connector.type.value,
                switchable=connector.switchable,
                identifier=connector.select_value,
                notes=connector.notes,
            )
            for connector in self.profile.inputs
        ]

    def _coex_inputs(self) -> list[InputState]:
        assert self.coex is not None
        payload = self.coex.input_sources()
        sources = payload.get("sources", payload) if isinstance(payload, dict) else payload
        states: list[InputState] = []
        for source in sources or []:
            states.append(
                InputState(
                    label=str(source.get("name") or source.get("id")),
                    type=str(source.get("type") or "unknown"),
                    switchable=True,
                    identifier=source.get("id"),
                    connected=source.get("connected"),
                )
            )
        return states

    def select_input(self, label: str) -> None:
        """Switch to an input by label, or by connector type when unambiguous."""
        if self.coex is not None:
            return self._coex_select_input(label)

        connector = self.profile.find_input(label)
        if connector is None:
            available = ", ".join(c.label for c in self.profile.inputs) or "none"
            raise NotSupported(
                f"{self.profile.name} has no input {label!r}; available: {available}"
            )
        return self.select_connector(connector)

    def select_connector(self, connector: InputConnector) -> None:
        if connector.select_value is None:
            raise CapabilityUnknown(
                f"the select code for {connector.label} on the {self.profile.name} "
                "has not been established -- capture NovaLCT switching to it "
                "(see docs/capture-workflow.md) rather than guessing a value"
            )
        if self.profile.input_register is None:
            raise CapabilityUnknown(
                f"the input register for the {self.profile.name} is unknown"
            )
        controller = self._require_controller("input switching")
        controller.write_uint(
            self.profile.input_register, connector.select_value, 1, Target.sending_card()
        )

    def _coex_select_input(self, label: str) -> None:
        assert self.coex is not None
        for state in self._coex_inputs():
            if str(state.label).lower() == label.strip().lower() or str(
                state.identifier
            ) == str(label):
                self.coex.select_input(int(state.identifier))  # type: ignore[arg-type]
                return
        raise NotSupported(f"no input {label!r} on {self.profile.name}")

    # --- outputs ------------------------------------------------------------

    def outputs(self) -> dict[str, Any]:
        """Output complement: Ethernet ports plus anything else the model has."""
        return {
            "ethernet_ports": self.profile.port_count,
            "fibre_ports": self.profile.fibre_ports,
            "other": [
                {
                    "label": output.label,
                    "type": output.type.value,
                    "count": output.count,
                    "loop_through": output.loop_through,
                }
                for output in self.profile.outputs
            ],
        }

    def cards(self, per_port: int | None = None) -> list[Target]:
        """Targets for every receiving card position this model can address.

        Without a topology read there is no way to know how many cards are on
        each port, so ``per_port`` is the caller's estimate; the point is that
        the *port* count comes from the model rather than an assumption. On a
        NovaPro UHD Jr that is 16 ports, not the 4 a VX4S-shaped guess produces.
        """
        count = per_port if per_port is not None else 1
        return [
            Target.receiving_card(port=port, index=index)
            for port in range(self.profile.port_count)
            for index in range(count)
        ]

    def receiving_cards(self, max_per_port: int = 64) -> list[Any]:
        """Find the receiving cards actually present behind this processor.

        Register bus only: the COEX HTTP API reports cabinets instead, which is
        the controller's own model of the same hardware and is available through
        :meth:`monitoring`.
        """
        if self.coex is not None:
            raise NotSupported(
                "COEX controllers report cabinets over HTTP; "
                "use monitoring() rather than walking the register bus"
            )
        controller = self._require_controller("receiving-card enumeration")
        return controller.enumerate_receiving_cards(
            ports=self.profile.port_count, max_per_port=max_per_port
        )

    # --- display ------------------------------------------------------------

    def set_display_mode(self, mode: DisplayMode | str) -> None:
        """Normal, blackout or freeze, by whatever mechanism the model uses.

        The value written is model-specific: a VX4S wants 2 for blackout where
        the COEX API wants 1. Resolving that here is the whole point of the
        profile carrying a :class:`~novasun.devices.DisplayControl`.
        """
        name = mode.name.lower() if isinstance(mode, DisplayMode) else str(mode).lower()
        if name not in ("normal", "blackout", "freeze"):
            raise ValueError(f"unknown display mode {mode!r}")

        if self.coex is not None:
            self.coex.set_display_mode(self.profile.display.value_for(name))
            return

        controller = self._require_controller("display control")
        control = self.profile.display
        if control.is_processor_level:
            assert control.register is not None
            controller.write_uint(
                control.register, control.value_for(name), 1, Target.sending_card()
            )
            return
        # Universal fallback: the receiving cards' own kill and lock registers.
        controller.blackout(name == "blackout")
        controller.freeze(name == "freeze")

    def blackout(self, enabled: bool = True) -> None:
        self.set_display_mode(DisplayMode.BLACKOUT if enabled else DisplayMode.NORMAL)

    def freeze(self, enabled: bool = True) -> None:
        self.set_display_mode(DisplayMode.FREEZE if enabled else DisplayMode.NORMAL)

    def set_test_pattern(self, pattern: "reg.TestPattern | str") -> None:
        """Show a built-in test pattern on the receiving cards.

        Register-bus only. The COEX HTTP API has a test-pattern endpoint, but
        its ``mode`` numbering is not documented in anything available here, so
        this refuses rather than sending a guessed integer to a live screen.
        """
        if self.coex is not None:
            raise CapabilityUnknown(
                "COEX test-pattern mode numbering has not been established; "
                "use the register bus, or capture VMP setting one "
                "(see docs/capture-workflow.md)"
            )
        controller = self._require_controller("test patterns")
        if isinstance(pattern, reg.TestPattern):
            resolved = pattern
        else:
            key = str(pattern).upper().replace("-", "_").replace(" ", "_")
            try:
                resolved = reg.TestPattern[key]
            except KeyError as exc:
                available = ", ".join(p.name.lower() for p in reg.TestPattern)
                raise ValueError(
                    f"unknown test pattern {pattern!r}; available: {available}"
                ) from exc
        controller.set_test_pattern(resolved)

    def set_panel_lock(self, locked: bool) -> None:
        """Lock the front-panel LCD and buttons, on models that support it."""
        if self.profile.panel_lock_register is None:
            raise NotSupported(f"{self.profile.name} has no documented panel lock")
        controller = self._require_controller("panel lock")
        controller.write_uint(
            self.profile.panel_lock_register, 1 if locked else 0, 1, Target.sending_card()
        )

    # --- brightness and monitoring -----------------------------------------

    def set_brightness(self, percent: float) -> None:
        if self.coex is not None:
            screens = self.coex.screens()
            identifiers = [
                screen["screenID"]
                for screen in (screens.get("screens", []) if isinstance(screens, dict) else [])
            ]
            if identifiers:
                self.coex.set_screen_brightness(identifiers, percent / 100)
                return
        controller = self._require_controller("brightness")
        controller.set_brightness(percent)

    def monitoring(self, port: int = 0, index: int = 0) -> ReceiverStatus | dict[str, Any]:
        if self.coex is not None:
            return self.coex.monitoring()
        controller = self._require_controller("monitoring")
        if port >= self.profile.port_count:
            raise ValueError(
                f"{self.profile.name} has {self.profile.port_count} ports; no port {port}"
            )
        return controller.read_receiver_monitoring(port, index)

    def presets(self) -> list[dict[str, Any]]:
        if self.coex is not None:
            payload = self.coex.presets()
            return payload.get("presets", []) if isinstance(payload, dict) else payload
        if not self.profile.presets:
            raise NotSupported(f"{self.profile.name} has no preset support")
        return []

    def apply_preset(self, identifier: int | str) -> None:
        if self.coex is not None:
            self.coex.apply_preset(str(identifier))
            return
        if not self.profile.presets:
            raise NotSupported(f"{self.profile.name} has no documented preset recall")
        controller = self._require_controller("presets")
        controller.apply_preset(int(identifier))

    def describe(self) -> str:
        if self.identification is not None:
            return self.identification.summary()
        return f"{self.profile.name} ({self.profile.family.value})"


__all__ = [
    "Processor",
    "InputState",
    "CapabilityUnknown",
    "NotSupported",
    "ConnectorType",
    "Family",
]
