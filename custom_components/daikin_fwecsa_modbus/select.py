"""Selects -- only with "allow writes" on.

The mode (coil 1): heating or cooling. The step fan speed (holding 11):
extra-low is offered on 4-speed units only, as on the unit's own keyboard.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FwecsaConfigEntry
from .coordinator import FwecsaCoordinator
from .entity import FwecsaEntity, FwecsaEntityDescription, remove_stale
from .registers import ENUMS, FAN_SPEEDS, MODES

PARALLEL_UPDATES = 1

SPEED_RAW = {name: raw for raw, name in FAN_SPEEDS.items()}


def fan_speeds(coordinator: FwecsaCoordinator) -> list[str]:
    """The speeds this unit offers, in the keyboard's order."""
    speeds = list(FAN_SPEEDS.values())
    if not coordinator.unit.has("four_speeds"):
        speeds.remove("extra_low")
    return speeds


def _current(key: str) -> Callable[[FwecsaCoordinator], str | None]:
    table = ENUMS[key]

    def current(coordinator: FwecsaCoordinator) -> str | None:
        raw = coordinator.data.values.get(key)
        return None if raw is None else table.get(raw)

    return current


@dataclass(frozen=True, kw_only=True)
class FwecsaSelectDescription(SelectEntityDescription, FwecsaEntityDescription):
    """A coil or holding register, written as one of its named values."""

    #: The options this unit offers, when that is fewer than all of them.
    options_fn: Callable[[FwecsaCoordinator], list[str]] | None = None


SELECTS: tuple[FwecsaSelectDescription, ...] = (
    FwecsaSelectDescription(key="mode", options=list(MODES.values()), value_fn=_current("mode")),
    FwecsaSelectDescription(key="fan_speed", options=list(FAN_SPEEDS.values()),
                            value_fn=_current("fan_speed"), options_fn=fan_speeds,
                            feature="step_fan"),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FwecsaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    if not coordinator.writes.allowed:
        remove_stale(hass, entry, "select")
        return
    async_add_entities(FwecsaSelect(coordinator, d, "select") for d in SELECTS)


class FwecsaSelect(FwecsaEntity, SelectEntity):
    entity_description: FwecsaSelectDescription

    def __init__(self, coordinator: FwecsaCoordinator, description: FwecsaSelectDescription,
                 domain: str) -> None:
        super().__init__(coordinator, description, domain)
        options_fn = description.options_fn
        self._attr_options = options_fn(coordinator) if options_fn else list(description.options)
        self._raw = {name: raw for raw, name in ENUMS[description.key].items()}

    @property
    def current_option(self) -> str | None:
        return self.entity_description.value_fn(self.coordinator)

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.writes.async_write(self.entity_description.key,
                                                  self._raw[option], self._context)
        await self.coordinator.async_request_refresh()
