"""The climate entity: what it shows, and what it writes for each switching mode."""

from __future__ import annotations

import pytest
from homeassistant.components.climate import (
    ATTR_FAN_MODE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODE,
    ATTR_PRESET_MODE,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate import (
    DOMAIN as CLIMATE,
)
from homeassistant.const import ATTR_ENTITY_ID, ATTR_TEMPERATURE
from homeassistant.exceptions import ServiceValidationError

ENTITY = "climate.fancoil"


async def _call(hass, service: str, **data) -> None:
    await hass.services.async_call(CLIMATE, service, {ATTR_ENTITY_ID: ENTITY, **data},
                                   blocking=True)
    await hass.async_block_till_done()


def _writes(fake) -> list[tuple[str, int, int]]:
    return [(table, address, raw) for _, table, address, raw in fake.writes]


async def test_state(hass, setup_integration):
    state = hass.states.get(ENTITY)
    assert state.state == HVACMode.HEAT
    assert state.attributes["current_temperature"] == 23.0
    assert state.attributes[ATTR_HVAC_ACTION] == HVACAction.IDLE   # fan off
    assert state.attributes["friendly_name"] == "Fancoil"


async def test_action_follows_the_fan_and_the_valve(hass, fake, setup_integration, advance):
    fake.tables["input"][4] = 2                 # low speed
    fake.tables["discrete"][25] = 1             # valve open
    await advance(10)
    assert hass.states.get(ENTITY).attributes[ATTR_HVAC_ACTION] == HVACAction.HEATING
    fake.tables["discrete"][25] = 0             # fan running on a closed valve
    await advance(10)
    assert hass.states.get(ENTITY).attributes[ATTR_HVAC_ACTION] == HVACAction.FAN
    fake.tables["discrete"][0] = 0
    await advance(10)
    state = hass.states.get(ENTITY)
    assert (state.state, state.attributes[ATTR_HVAC_ACTION]) == (HVACMode.OFF, HVACAction.OFF)


async def test_keyboard_switching_offers_heat_and_cool(hass, fake, writes_on, setup_integration):
    state = hass.states.get(ENTITY)
    assert state.attributes["hvac_modes"] == [HVACMode.OFF, HVACMode.HEAT, HVACMode.COOL]
    assert state.attributes["fan_modes"] == ["low", "medium", "high", "auto"]  # 3 speeds
    assert (state.attributes["min_temp"], state.attributes["max_temp"]) == (5.0, 30.0)

    await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 21.5})
    assert _writes(fake) == [("holding", 3, 215)]       # winter: the heating setpoint
    assert hass.states.get(ENTITY).attributes[ATTR_TEMPERATURE] == 21.5

    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: HVACMode.COOL})
    assert _writes(fake)[1:] == [("coil", 1, 0)]        # power is on already
    assert hass.states.get(ENTITY).state == HVACMode.COOL

    await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 25})
    assert _writes(fake)[2:] == [("holding", 0, 250)]   # summer: the cooling setpoint

    await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: HVACMode.OFF})
    assert _writes(fake)[3:] == [("coil", 0, 0)]
    assert hass.states.get(ENTITY).state == HVACMode.OFF


async def test_mode_and_temperature_in_one_call(hass, fake, writes_on, setup_integration):
    await _call(hass, "set_temperature",
                **{ATTR_TEMPERATURE: 26, ATTR_HVAC_MODE: HVACMode.COOL})
    # The setpoint goes to the season just commanded, not the one last read.
    assert _writes(fake) == [("coil", 1, 0), ("holding", 0, 260)]


async def test_auto_switching_writes_the_single_setpoint(hass, fake, auto_switching,
                                                         setup_integration):
    state = hass.states.get(ENTITY)
    assert state.state == HVACMode.AUTO
    assert state.attributes["hvac_modes"] == [HVACMode.OFF, HVACMode.AUTO]
    assert (state.attributes["min_temp"], state.attributes["max_temp"]) == (5.0, 35.0)
    await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 24})
    assert _writes(fake) == [("holding", 6, 240)]
    assert hass.states.get(ENTITY).attributes[ATTR_TEMPERATURE] == 24.0
    with pytest.raises(ServiceValidationError):
        await _call(hass, "set_hvac_mode", **{ATTR_HVAC_MODE: HVACMode.COOL})


async def test_fan_and_preset(hass, fake, writes_on, setup_integration):
    await _call(hass, "set_fan_mode", **{ATTR_FAN_MODE: "medium"})
    await _call(hass, "set_preset_mode", **{ATTR_PRESET_MODE: "eco"})
    assert _writes(fake) == [("holding", 10, 2), ("coil", 2, 1)]
    state = hass.states.get(ENTITY)
    assert (state.attributes[ATTR_FAN_MODE], state.attributes[ATTR_PRESET_MODE]) == (
        "medium", "eco")
    with pytest.raises(ServiceValidationError):
        await _call(hass, "set_fan_mode", **{ATTR_FAN_MODE: "extra_low"})  # 4-speed only


async def test_read_only_refuses_commands(hass, fake, setup_integration):
    with pytest.raises(ServiceValidationError):
        await _call(hass, "set_temperature", **{ATTR_TEMPERATURE: 22})
    assert fake.writes == []
