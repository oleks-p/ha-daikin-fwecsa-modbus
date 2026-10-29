"""The step fan speed (holding 11) as a select -- only with "allow writes" on.

Extra-low is offered on 4-speed units only, as on the unit's own keyboard.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FwecsaConfigEntry
from .coordinator import FwecsaCoordinator
from .entity import FwecsaEntity, FwecsaEntityDescription, remove_stale
from .registers import FAN_SPEEDS

PARALLEL_UPDATES = 1

SPEED_RAW = {name: raw for raw, name in FAN_SPEEDS.items()}


def fan_speeds(coordinator: FwecsaCoordinator) -> list[str]:
    """The speeds this unit offers, in the keyboard's order."""
    speeds = list(FAN_SPEEDS.values())
    if not coordinator.unit.has("four_speeds"):
        speeds.remove("extra_low")
    return speeds


def _current(coordinator: FwecsaCoordinator) -> str | None:
    raw = coordinator.data.values.get("fan_speed")
    return None if raw is None else FAN_SPEEDS.get(raw)


@dataclass(frozen=True, kw_only=True)
class FwecsaSelectDescription(SelectEntityDescription, FwecsaEntityDescription):
    """The fan speed."""


FAN_SPEED = FwecsaSelectDescription(key="fan_speed", options=list(FAN_SPEEDS.values()),
                                    value_fn=_current, feature="step_fan")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FwecsaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    if not coordinator.writes.allowed:
        remove_stale(hass, entry, "select")
        return
    async_add_entities([FwecsaFanSpeed(coordinator, FAN_SPEED, "select")])


class FwecsaFanSpeed(FwecsaEntity, SelectEntity):
    entity_description: FwecsaSelectDescription

    def __init__(self, coordinator: FwecsaCoordinator, description: FwecsaSelectDescription,
                 domain: str) -> None:
        super().__init__(coordinator, description, domain)
        self._attr_options = fan_speeds(coordinator)

    @property
    def current_option(self) -> str | None:
        return self.entity_description.value_fn(self.coordinator)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.writes.async_write("fan_speed", SPEED_RAW[option], self._context)
        await self.coordinator.async_request_refresh()
