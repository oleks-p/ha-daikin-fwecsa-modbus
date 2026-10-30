"""The fancoil as a climate entity -- read-only unless writes are allowed.

What it shows comes from the unit's own status, not from what was last
written: on/off is discrete input 0 (which also follows the keyboard, the time
slots and the remote contact), heating or cooling is discrete input 1, and the
target is input register 9, the setpoint the unit is working to.

What it may change depends on the unit's "Switching Summer/Winter" parameter,
which Modbus cannot read, so the entry's options say what it is set to:

* from keyboard/serial (factory default): off, heat and cool; the target is
  holding 0 (cooling) or 3 (heating), whichever season the unit is in;
* from digital input: the contact sets the season, so off and that season only;
* auto on water or air temperature: the unit decides, so off and auto; the
  target is the single setpoint, holding 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    PRESET_ECO,
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityDescription,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import FwecsaConfigEntry
from .const import (
    AUTO_SWITCHINGS,
    CONF_ENTITY_PREFIX,
    DEFAULT_ENTITY_PREFIX,
    DOMAIN,
    SWITCHING_DIGITAL_INPUT,
)
from .coordinator import FwecsaCoordinator
from .entity import FwecsaEntity, FwecsaEntityDescription, value
from .registers import FAN_SPEEDS
from .select import SPEED_RAW, fan_speeds

PARALLEL_UPDATES = 1  # one write at a time: they share one bus

#: Used when the unit's own limits have not been read.
FALLBACK_MIN, FALLBACK_MAX = 5.0, 35.0


@dataclass(frozen=True, kw_only=True)
class FwecsaClimateDescription(ClimateEntityDescription, FwecsaEntityDescription):
    """The one climate entity."""


FANCOIL = FwecsaClimateDescription(key="fancoil", value_fn=value("unit_on"))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FwecsaConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([FwecsaClimate(entry.runtime_data.coordinator, FANCOIL, "climate")])


class FwecsaClimate(FwecsaEntity, ClimateEntity):
    entity_description: FwecsaClimateDescription
    _attr_name = None  # the device's name
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_precision = 0.1
    _attr_target_temperature_step = 0.5

    def __init__(self, coordinator: FwecsaCoordinator, description: FwecsaClimateDescription,
                 domain: str) -> None:
        super().__init__(coordinator, description, domain)
        # climate.fancoil, not climate.fancoil_fancoil.
        prefix = coordinator.config_entry.data.get(CONF_ENTITY_PREFIX, DEFAULT_ENTITY_PREFIX)
        self.entity_id = f"climate.{prefix}"
        unit = coordinator.unit
        self._step_fan = not unit.has("modulating_fan")
        self._attr_fan_modes = fan_speeds(coordinator) if self._step_fan else None
        self._humidity = unit.has("humidity_probe_installed")

    @property
    def _values(self) -> dict[str, Any]:
        return self.coordinator.data.values

    @property
    def _writes(self) -> bool:
        return self.coordinator.writes.allowed

    @property
    def _auto(self) -> bool:
        return self.coordinator.switching in AUTO_SWITCHINGS

    @property
    def _season_mode(self) -> HVACMode | None:
        heating = self._values.get("mode_in_use")
        return None if heating is None else HVACMode.HEAT if heating else HVACMode.COOL

    # -- state ------------------------------------------------------------------

    @property
    def hvac_mode(self) -> HVACMode | None:
        on = self._values.get("unit_on")
        if on is None:
            return None
        if not on:
            return HVACMode.OFF
        return HVACMode.AUTO if self._auto else self._season_mode

    @property
    def hvac_modes(self) -> list[HVACMode]:
        if not self._writes:
            # Only the mode the unit is in: nothing else can be chosen from here.
            mode = self.hvac_mode
            return [mode] if mode is not None else []
        if self._auto:
            return [HVACMode.OFF, HVACMode.AUTO]
        if self.coordinator.switching == SWITCHING_DIGITAL_INPUT:
            season = self._season_mode
            return [HVACMode.OFF, season] if season else [HVACMode.OFF]
        return [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]

    @property
    def hvac_action(self) -> HVACAction | None:
        values = self._values
        on = values.get("unit_on")
        if on is None:
            return None
        if not on:
            return HVACAction.OFF
        if values.get("dehumidifying"):
            return HVACAction.DRYING
        if self._fan_running():
            if values.get("valve_present") and values.get("valve_open") is False:
                return HVACAction.FAN
            if values.get("mode_in_use") is None:
                return None
            return HVACAction.HEATING if values.get("mode_in_use") else HVACAction.COOLING
        if values.get("heater_on"):
            return HVACAction.HEATING
        return HVACAction.IDLE

    def _fan_running(self) -> bool:
        values = self._values
        if self._step_fan:
            return (values.get("fan_status") or 0) > 0
        return (values.get("modulating_fan_output") or 0) > 0

    @property
    def current_temperature(self) -> float | None:
        return self._values.get("room_temperature")

    @property
    def current_humidity(self) -> float | None:
        return self._values.get("room_humidity") if self._humidity else None

    @property
    def target_temperature(self) -> float | None:
        active = self._values.get("active_setpoint")
        if active is not None:
            return active
        key = self._setpoint_key()
        return self._values.get(key) if key else None

    @property
    def min_temp(self) -> float:
        return self._limit("min", min, FALLBACK_MIN)

    @property
    def max_temp(self) -> float:
        return self._limit("max", max, FALLBACK_MAX)

    def _limit(self, end: str, pick, fallback: float) -> float:
        """The unit's own setpoint limits for the season it is in (both, in auto)."""
        heating = self._values.get("mode_in_use")
        seasons = ("cooling", "heating") if self._auto or heating is None else (
            ("heating",) if heating else ("cooling",))
        limits = [self._values.get(f"{s}_setpoint_{end}") for s in seasons]
        limits = [v for v in limits if v is not None]
        return pick(limits) if limits else fallback

    @property
    def fan_mode(self) -> str | None:
        if not self._step_fan:
            return None
        raw = self._values.get("fan_speed")
        return None if raw is None else FAN_SPEEDS.get(raw)

    @property
    def preset_modes(self) -> list[str] | None:
        return [PRESET_NONE, PRESET_ECO] if self._writes else None

    @property
    def preset_mode(self) -> str | None:
        economy = self._values.get("economy_on")
        return None if economy is None else PRESET_ECO if economy else PRESET_NONE

    @property
    def supported_features(self) -> ClimateEntityFeature:
        if not self._writes:
            return ClimateEntityFeature(0)
        features = (ClimateEntityFeature.TARGET_TEMPERATURE | ClimateEntityFeature.TURN_ON
                    | ClimateEntityFeature.TURN_OFF | ClimateEntityFeature.PRESET_MODE)
        if self._step_fan:
            features |= ClimateEntityFeature.FAN_MODE
        return features

    # -- commands ---------------------------------------------------------------

    def _setpoint_key(self, heating: bool | None = None) -> str | None:
        """The holding register the target is written to, by the switching option.

        ``heating``: the season just commanded, when it has not been read back yet.
        """
        if self._auto:
            return "single_setpoint"
        if heating is None:
            heating = self._values.get("mode_in_use")
        if heating is None:
            return None
        return "heating_setpoint" if heating else "cooling_setpoint"

    async def _write(self, key: str, value: float) -> None:
        await self.coordinator.writes.async_write(key, value, self._context)

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        await self._set_hvac_mode(hvac_mode)
        await self.coordinator.async_request_refresh()

    async def _set_hvac_mode(self, hvac_mode: HVACMode) -> bool | None:
        """Command the mode; returns the season commanded, if it changed."""
        if hvac_mode not in self.hvac_modes:
            raise ServiceValidationError(translation_domain=DOMAIN,
                                         translation_key="hvac_mode_unavailable",
                                         translation_placeholders={"mode": str(hvac_mode)})
        if hvac_mode is HVACMode.OFF:
            await self._write("power", 0)
            return None
        season = None
        if hvac_mode in (HVACMode.HEAT, HVACMode.COOL) and hvac_mode != self._season_mode:
            # The season first: switching on into the wrong one would start the
            # coil on the wrong water for a poll.
            season = hvac_mode is HVACMode.HEAT
            await self._write("mode", int(season))
        await self._write("power", 1)
        return season

    async def async_turn_on(self) -> None:
        await self._write("power", 1)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        await self._write("power", 0)
        await self.coordinator.async_request_refresh()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        season = None
        if (mode := kwargs.get(ATTR_HVAC_MODE)) is not None:
            season = await self._set_hvac_mode(mode)
        if (temperature := kwargs.get(ATTR_TEMPERATURE)) is not None:
            key = self._setpoint_key(season)
            if key is None:
                raise ServiceValidationError(translation_domain=DOMAIN,
                                             translation_key="no_season")
            await self._write(key, round(float(temperature), 1))
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        if fan_mode not in SPEED_RAW or fan_mode not in (self.fan_modes or []):
            raise ServiceValidationError(translation_domain=DOMAIN,
                                         translation_key="fan_mode_unavailable",
                                         translation_placeholders={"mode": fan_mode})
        await self._write("fan_speed", SPEED_RAW[fan_mode])
        await self.coordinator.async_request_refresh()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        await self._write("economy", int(preset_mode == PRESET_ECO))
        await self.coordinator.async_request_refresh()
