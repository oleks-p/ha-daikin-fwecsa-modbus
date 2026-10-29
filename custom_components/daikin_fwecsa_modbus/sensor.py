"""Sensor entities: every input register, and every holding register read-only.

The holding registers are here as well as on the number and select platforms:
a sensor exists with writes off, and keeps long-term statistics, which a
number has none of.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FwecsaConfigEntry
from .coordinator import FwecsaCoordinator
from .entity import FwecsaEntity, FwecsaEntityDescription, value
from .registers import ENUMS

PARALLEL_UPDATES = 0  # all reads go through the coordinator

DIAGNOSTIC = EntityCategory.DIAGNOSTIC
MEASUREMENT = SensorStateClass.MEASUREMENT
HUMIDITY = "humidity_probe_installed"


@dataclass(frozen=True, kw_only=True)
class FwecsaSensorDescription(SensorEntityDescription, FwecsaEntityDescription):
    """A sensor and where its value comes from."""


def _temperature(key: str, *, statistics: bool = True, **kwargs: Any) -> FwecsaSensorDescription:
    return FwecsaSensorDescription(
        key=key,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        state_class=MEASUREMENT if statistics else None,
        suggested_display_precision=1,
        value_fn=value(key),
        **kwargs,
    )


def _limit(key: str) -> FwecsaSensorDescription:
    return _temperature(key, statistics=False, entity_category=DIAGNOSTIC)


def _percent(key: str, *, statistics: bool = True, **kwargs: Any) -> FwecsaSensorDescription:
    return FwecsaSensorDescription(
        key=key, native_unit_of_measurement=PERCENTAGE,
        state_class=MEASUREMENT if statistics else None, value_fn=value(key), **kwargs)


def _enum(key: str, **kwargs: Any) -> FwecsaSensorDescription:
    table = ENUMS[key]

    def state(coordinator: FwecsaCoordinator) -> str | None:
        raw = coordinator.data.values.get(key)
        return None if raw is None else table.get(raw)

    return FwecsaSensorDescription(key=key, device_class=SensorDeviceClass.ENUM,
                                   options=list(table.values()), value_fn=state, **kwargs)


SENSORS: tuple[FwecsaSensorDescription, ...] = (
    # -- input registers ----------------------------------------------------
    _temperature("room_temperature"),
    FwecsaSensorDescription(
        key="room_humidity", native_unit_of_measurement=PERCENTAGE,
        device_class=SensorDeviceClass.HUMIDITY, state_class=MEASUREMENT,
        value_fn=value("room_humidity"), feature=HUMIDITY),
    _temperature("water_temperature"),
    _temperature("hot_water_temperature", feature="four_pipes"),
    _enum("fan_status"),
    _percent("modulating_fan_output", feature="modulating_fan"),
    _percent("analog_output_1", feature="analog_outputs"),
    _percent("analog_output_2", feature="analog_outputs"),
    _percent("analog_output_3", feature="analog_outputs"),
    _temperature("active_setpoint"),
    _temperature("cooling_setpoint_status", statistics=False, entity_category=DIAGNOSTIC),
    _temperature("heating_setpoint_status", statistics=False, entity_category=DIAGNOSTIC),
    _temperature("single_setpoint_status", statistics=False, entity_category=DIAGNOSTIC),
    _percent("active_humidity_setpoint", feature=HUMIDITY),
    _enum("valve_type", entity_category=DIAGNOSTIC),
    # -- holding registers, read-only mirrors ---------------------------------
    _temperature("cooling_setpoint"),
    _limit("cooling_setpoint_min"),
    _limit("cooling_setpoint_max"),
    _temperature("heating_setpoint"),
    _limit("heating_setpoint_min"),
    _limit("heating_setpoint_max"),
    _temperature("single_setpoint"),
    _percent("humidity_setpoint", feature=HUMIDITY),
    _percent("humidity_setpoint_min", statistics=False, entity_category=DIAGNOSTIC,
             feature=HUMIDITY),
    _percent("humidity_setpoint_max", statistics=False, entity_category=DIAGNOSTIC,
             feature=HUMIDITY),
    _enum("fan_speed", feature="step_fan"),
    _percent("modulating_fan_speed", feature="modulating_fan"),
    # -- link health -----------------------------------------------------------
    FwecsaSensorDescription(
        key="last_successful_read", device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=DIAGNOSTIC, value_fn=lambda c: c.last_success_at),
    FwecsaSensorDescription(
        key="read_failures", entity_category=DIAGNOSTIC, value_fn=lambda c: c.read_failures),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FwecsaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data.coordinator
    async_add_entities(FwecsaSensor(coordinator, d, "sensor") for d in SENSORS)


class FwecsaSensor(FwecsaEntity, SensorEntity):
    entity_description: FwecsaSensorDescription

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator)
