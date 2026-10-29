"""Every numeric holding register as a number -- only with "allow writes" on.

Writes go out as FC16 and are read back (writes.py). The read-only sensor of
the same key stays: it carries the long-term statistics, which a number has
none of.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import (
    NumberDeviceClass,
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FwecsaConfigEntry
from .entity import FwecsaEntity, FwecsaEntityDescription, remove_stale, value
from .registers import BY_KEY, WRITE_SPECS, WriteSpec

PARALLEL_UPDATES = 1  # one write at a time: they share one bus

#: The setpoints themselves: the rest (limits) are set once, on a service page.
PRIMARY = {"cooling_setpoint", "heating_setpoint", "single_setpoint", "humidity_setpoint",
           "modulating_fan_speed"}
FEATURES = {
    "humidity_setpoint": "humidity_probe_installed",
    "humidity_setpoint_min": "humidity_probe_installed",
    "humidity_setpoint_max": "humidity_probe_installed",
    "modulating_fan_speed": "modulating_fan",
}


@dataclass(frozen=True, kw_only=True)
class FwecsaNumberDescription(NumberEntityDescription, FwecsaEntityDescription):
    """A writable holding register."""


def _describe(spec: WriteSpec) -> FwecsaNumberDescription:
    temperature = BY_KEY[spec.key].scale != 1.0
    return FwecsaNumberDescription(
        key=spec.key,
        native_min_value=spec.minimum,
        native_max_value=spec.maximum,
        native_step=spec.step,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS if temperature else PERCENTAGE,
        device_class=NumberDeviceClass.TEMPERATURE if temperature else None,
        mode=NumberMode.BOX,
        entity_category=None if spec.key in PRIMARY else EntityCategory.CONFIG,
        value_fn=value(spec.key),
        feature=FEATURES.get(spec.key),
    )


NUMBERS: tuple[FwecsaNumberDescription, ...] = tuple(
    _describe(spec) for spec in WRITE_SPECS.values() if spec.platform == "number")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FwecsaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    if not coordinator.writes.allowed:
        remove_stale(hass, entry, "number")
        return
    async_add_entities(FwecsaNumber(coordinator, d, "number") for d in NUMBERS)


class FwecsaNumber(FwecsaEntity, NumberEntity):
    entity_description: FwecsaNumberDescription

    @property
    def native_value(self) -> float | None:
        return self.entity_description.value_fn(self.coordinator)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.writes.async_write(self.entity_description.key, value,
                                                  self._context)
        await self.coordinator.async_request_refresh()
