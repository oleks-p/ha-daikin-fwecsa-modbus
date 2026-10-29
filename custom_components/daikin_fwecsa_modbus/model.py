"""Which unit is on the other end, and how it is configured.

The FWECSA has no identity registers: no model code, no firmware version. What
it does have is its own configuration, readable as discrete inputs -- number of
speeds and pipes, fan type, which probes, heaters and valve are fitted -- and
that is what is read here. It decides which entities are enabled by default and
which fan speeds the climate entity offers.

Whether the address is an FWECSA at all is judged by the shape of the answer:
the 31 discrete inputs and the 15 input registers the manual lists must read,
and the enumerated values must be in range.
"""

from __future__ import annotations

from dataclasses import dataclass

from .registers import TABLE_SIZES, VALVE_TYPES, Table
from .transport import FwecsaBus, FwecsaIllegalError

#: Discrete inputs that describe the unit, by key -> address.
CONFIG_BITS: dict[str, int] = {
    "four_speeds": 9,
    "four_pipes": 10,
    "modulating_fan": 11,
    "board_probe": 12,
    "heaters_installed": 13,
    "humidity_probe_installed": 14,
    "water_probe_present": 22,
    "hot_water_probe_present": 23,
    "valve_present": 29,
}
VALVE_TYPE_ADDRESS = 14
FAN_STATUS_ADDRESS = 4


class NotAnFwecsa(Exception):
    """The address answered, but not like an FWECSA."""


@dataclass(frozen=True, slots=True)
class UnitConfig:
    """The unit's configuration as it reports it."""

    bits: dict[str, bool]
    valve_type: int

    def has(self, key: str) -> bool:
        return self.bits.get(key, False)

    @property
    def speeds(self) -> int:
        return 4 if self.has("four_speeds") else 3

    @property
    def pipes(self) -> int:
        return 4 if self.has("four_pipes") else 2

    @property
    def features(self) -> frozenset[str]:
        """Feature names that entity descriptions can depend on."""
        features = {key for key, on in self.bits.items() if on}
        features.add("modulating_fan" if self.has("modulating_fan") else "step_fan")
        if self.has("modulating_fan") or self.valve_type == 2:
            features.add("analog_outputs")
        if self.valve_type in (1, 2) or self.has("valve_present"):
            features.add("valve")
        return frozenset(features)

    @property
    def summary(self) -> str:
        fan = "modulating fan" if self.has("modulating_fan") else f"{self.speeds} speeds"
        valve = VALVE_TYPES.get(self.valve_type, str(self.valve_type)).replace("_", "/")
        return f"{fan}, {self.pipes} pipes, valve {valve}"

    def as_dict(self) -> dict[str, object]:
        return {**self.bits, "valve_type": self.valve_type, "speeds": self.speeds,
                "pipes": self.pipes, "features": sorted(self.features)}


async def async_identify(bus: FwecsaBus, slave: int) -> UnitConfig:
    """Read the configuration bits. Raises NotAnFwecsa.

    Link failures propagate as FwecsaTransientError: the caller decides between
    "try again later" (setup) and "cannot connect" (config flow).
    """
    try:
        bits = await bus.read(slave, Table.DISCRETE, 0, TABLE_SIZES[Table.DISCRETE])
        words = await bus.read(slave, Table.INPUT, 0, TABLE_SIZES[Table.INPUT])
    except FwecsaIllegalError as err:
        raise NotAnFwecsa(str(err)) from err
    valve_type = words[VALVE_TYPE_ADDRESS]
    if valve_type not in VALVE_TYPES:
        raise NotAnFwecsa(f"input register {VALVE_TYPE_ADDRESS} (valve type) reads {valve_type}")
    if words[FAN_STATUS_ADDRESS] > 4:
        raise NotAnFwecsa(f"input register {FAN_STATUS_ADDRESS} (fan status) reads "
                          f"{words[FAN_STATUS_ADDRESS]}")
    return UnitConfig({key: bool(bits[address]) for key, address in CONFIG_BITS.items()},
                      valve_type)
