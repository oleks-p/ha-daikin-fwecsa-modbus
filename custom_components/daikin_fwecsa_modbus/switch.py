"""Every coil as a switch -- only with "allow writes" on. Coil 1, the mode, is a
select instead (select.py).

Writes go out as FC15 and are read back (writes.py). The state shown is the
coil as the unit reads it back; what the unit is doing as a result is in the
discrete inputs, which follow on the next poll.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FwecsaConfigEntry
from .binary_sensor import FEATURES
from .entity import FwecsaEntity, FwecsaEntityDescription, remove_stale, value
from .registers import COILS, WRITE_SPECS

PARALLEL_UPDATES = 1  # one write at a time: they share one bus

#: Everyday controls; the rest are set once, on a service page.
PRIMARY = {"power", "economy"}


@dataclass(frozen=True, kw_only=True)
class FwecsaSwitchDescription(SwitchEntityDescription, FwecsaEntityDescription):
    """A coil."""


SWITCHES: tuple[FwecsaSwitchDescription, ...] = tuple(
    FwecsaSwitchDescription(
        key=reg.key,
        entity_category=None if reg.key in PRIMARY else EntityCategory.CONFIG,
        value_fn=value(reg.key),
        feature=FEATURES.get(reg.key),
    )
    for reg in COILS
    if WRITE_SPECS[reg.key].platform == "switch"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FwecsaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    if not coordinator.writes.allowed:
        remove_stale(hass, entry, "switch")
        return
    async_add_entities(FwecsaSwitch(coordinator, d, "switch") for d in SWITCHES)


class FwecsaSwitch(FwecsaEntity, SwitchEntity):
    entity_description: FwecsaSwitchDescription

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator)

    async def _set(self, on: bool) -> None:
        await self.coordinator.writes.async_write(self.entity_description.key, int(on),
                                                  self._context)
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
