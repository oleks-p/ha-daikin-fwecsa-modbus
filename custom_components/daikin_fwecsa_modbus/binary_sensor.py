"""Binary sensors: every discrete input, and every coil read-only.

The coils are here as well as on the switch platform so their state is visible
with writes off -- all but coil 1, the mode, which is a sensor like its status
input: heating or cooling says more than on or off. They are diagnostic: what the unit is actually doing is in the
discrete inputs ("unit on", "economy active"), which also follow the keyboard,
the time slots and the remote contacts.
"""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FwecsaConfigEntry
from .entity import FwecsaEntity, FwecsaEntityDescription, value
from .registers import COILS, ENUMS

DIAGNOSTIC = EntityCategory.DIAGNOSTIC
PROBLEM = BinarySensorDeviceClass.PROBLEM
RUNNING = BinarySensorDeviceClass.RUNNING

#: Coils and inputs that only mean something on a unit with the part fitted.
FEATURES = {
    "electric_heater": "heaters_installed",
    "master_electric_heater": "heaters_installed",
    "heater_on": "heaters_installed",
    "humidity_control": "humidity_probe_installed",
    "master_humidity": "humidity_probe_installed",
    "humidity_probe_alarm": "humidity_probe_installed",
    "hot_water_probe_alarm": "four_pipes",
    "modulating_fan_auto": "modulating_fan",
}


@dataclass(frozen=True, kw_only=True)
class FwecsaBinaryDescription(BinarySensorEntityDescription, FwecsaEntityDescription):
    """A binary sensor and where its value comes from."""


def _bit(key: str, **kwargs) -> FwecsaBinaryDescription:
    return FwecsaBinaryDescription(key=key, value_fn=value(key), feature=FEATURES.get(key),
                                   **kwargs)


def _config(key: str) -> FwecsaBinaryDescription:
    """How the unit is built and set up: fixed, so diagnostic."""
    return _bit(key, entity_category=DIAGNOSTIC)


BINARY_SENSORS: tuple[FwecsaBinaryDescription, ...] = (
    # -- discrete inputs ------------------------------------------------------
    _bit("unit_on", device_class=BinarySensorDeviceClass.POWER),
    _bit("economy_on"),
    _bit("anti_freeze_on"),
    _bit("alarm", device_class=PROBLEM),
    _bit("room_probe_alarm", device_class=PROBLEM),
    _bit("water_probe_alarm", device_class=PROBLEM),
    _bit("hot_water_probe_alarm", device_class=PROBLEM),
    _bit("humidity_probe_alarm", device_class=PROBLEM),
    _config("four_speeds"),
    _config("four_pipes"),
    _config("modulating_fan"),
    _config("board_probe"),
    _config("heaters_installed"),
    _config("humidity_probe_installed"),
    *(_bit(f"output_{n}", entity_category=DIAGNOSTIC) for n in range(1, 8)),
    _config("water_probe_present"),
    _config("hot_water_probe_present"),
    _bit("dehumidifying", device_class=RUNNING),
    # No OPENING class: Home Assistant's Security view lists those, as it would
    # a door. Open and closed come from the translations instead.
    _bit("valve_open"),
    _bit("off_by_contact"),
    _bit("fan_auto_mode"),
    _bit("heater_on", device_class=RUNNING),
    _config("valve_present"),
    _config("economy_by_contact"),
    # -- coils, read-only -------------------------------------------------------
    *(_bit(reg.key, entity_category=DIAGNOSTIC) for reg in COILS if reg.key not in ENUMS),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FwecsaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(FwecsaBinarySensor(coordinator, d, "binary_sensor")
                       for d in BINARY_SENSORS)


class FwecsaBinarySensor(FwecsaEntity, BinarySensorEntity):
    entity_description: FwecsaBinaryDescription

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator)
