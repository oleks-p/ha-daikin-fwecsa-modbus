"""The write path: opt-in, range, read-back, no wear, rate limits, consent."""

from __future__ import annotations

import pytest
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from custom_components.daikin_fwecsa_modbus.const import EVENT_WRITTEN, WRITE_MIN_INTERVAL


def _gate(entry):
    return entry.runtime_data.coordinator.writes


async def test_off_by_default(hass, fake, setup_integration):
    with pytest.raises(ServiceValidationError, match="writes_disabled|Allow writes"):
        await _gate(setup_integration).async_write("power", 0)
    assert fake.writes == []


async def test_a_number_writes_and_reads_back(hass, fake, writes_on, setup_integration):
    events = []
    hass.bus.async_listen(EVENT_WRITTEN, events.append)
    await hass.services.async_call("number", "set_value",
                                   {"entity_id": "number.fancoil_heating_setpoint", "value": 20.5},
                                   blocking=True)
    await hass.async_block_till_done()
    assert [w[1:] for w in fake.writes] == [("holding", 3, 205)]
    assert hass.states.get("number.fancoil_heating_setpoint").state == "20.5"
    assert events[0].data["old"] == 21.0 and events[0].data["applied"] is True


async def test_a_switch_writes_a_coil(hass, fake, writes_on, setup_integration):
    await hass.services.async_call("switch", "turn_on",
                                   {"entity_id": "switch.fancoil_keyboard_lock"}, blocking=True)
    await hass.async_block_till_done()
    assert [w[1:] for w in fake.writes] == [("coil", 14, 1)]
    assert hass.states.get("switch.fancoil_keyboard_lock").state == "on"


async def test_the_same_value_is_not_written(hass, fake, writes_on, setup_integration):
    await _gate(setup_integration).async_write("single_setpoint", 23.0)
    await _gate(setup_integration).async_write("power", 1)
    assert fake.writes == []


async def test_range_and_step(hass, fake, writes_on, setup_integration):
    gate = _gate(setup_integration)
    for key, value in (("heating_setpoint", 45), ("heating_setpoint", 20.05), ("fan_speed", 5)):
        with pytest.raises(ServiceValidationError):
            await gate.async_write(key, value)
    with pytest.raises(ServiceValidationError):
        await gate.async_write("room_temperature", 20)      # an input register
    assert fake.writes == []


async def test_rate_limited(hass, fake, writes_on, setup_integration, freezer):
    gate = _gate(setup_integration)
    await gate.async_write("cooling_setpoint", 25)
    with pytest.raises(HomeAssistantError, match="rate_limited|Too many"):
        await gate.async_write("cooling_setpoint", 26)
    freezer.tick(WRITE_MIN_INTERVAL)
    await gate.async_write("cooling_setpoint", 26)
    assert [w[3] for w in fake.writes] == [250, 260]


async def test_not_applied_names_the_consent_coil(hass, fake, writes_on, setup_integration):
    fake.ignore.add(("coil", 2))                # economy: acknowledged, not kept
    with pytest.raises(HomeAssistantError) as err:
        await _gate(setup_integration).async_write("economy", 1)
    assert err.value.translation_key == "write_not_applied_consent"
    assert err.value.translation_placeholders["consent"] == "master_economy"

    fake.ignore.add(("holding", 6))             # setpoint: its consent coil is on
    with pytest.raises(HomeAssistantError) as err:
        await _gate(setup_integration).async_write("single_setpoint", 22)
    assert err.value.translation_key == "write_not_applied"
