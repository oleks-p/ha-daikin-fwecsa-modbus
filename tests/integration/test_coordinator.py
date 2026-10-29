"""Polling: outages, refused blocks, and setup failures."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import STATE_UNAVAILABLE

from custom_components.daikin_fwecsa_modbus.const import DEFAULT_UNAVAILABLE_AFTER

ROOM = "sensor.fancoil_room_temperature"


async def test_four_requests_a_poll(hass, fake, setup_integration, advance):
    fake.requests.clear()
    await advance(10)
    assert [(fc, a, n) for fc, _, a, n in fake.requests] == [
        (1, 0, 18), (2, 0, 31), (3, 0, 12), (4, 0, 15)]


async def test_a_short_outage_keeps_the_last_values(hass, fake, setup_integration, advance):
    fake.offline = True
    await advance(DEFAULT_UNAVAILABLE_AFTER - 10)
    assert hass.states.get(ROOM).state == "23.0"
    await advance(20)
    assert hass.states.get(ROOM).state == STATE_UNAVAILABLE
    fake.offline = False
    fake.tables["input"][0] = 225
    await advance(10)
    assert hass.states.get(ROOM).state == "22.5"


async def test_a_unit_refusing_whole_tables_is_not_set_up(hass, fake, config_entry,
                                                          modbus_clients, freezer):
    fake.refuse_blocks.add("input")
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    # identify reads the input table whole: an FWECSA that refuses it is not one we know
    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_a_refused_block_after_setup(hass, fake, setup_integration, advance):
    fake.refuse_blocks.add("holding")
    await advance(10)
    coordinator = setup_integration.runtime_data.coordinator
    assert coordinator.split_blocks == ["holding 0..11"]
    assert hass.states.get("sensor.fancoil_single_setpoint").state == "23.0"
    fake.requests.clear()
    await advance(10)
    assert sum(1 for fc, *_ in fake.requests if fc == 3) == 12


async def test_no_answer_at_setup_retries(hass, fake, config_entry, modbus_clients):
    fake.offline = True
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_RETRY


async def test_something_else_at_the_address(hass, fake, config_entry, modbus_clients):
    fake.tables["input"][14] = 7                # no such valve type
    assert not await hass.config_entries.async_setup(config_entry.entry_id)
    assert config_entry.state is ConfigEntryState.SETUP_ERROR


async def test_unload_closes_the_link(hass, setup_integration, modbus_clients):
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    assert modbus_clients[-1].closes >= 1
