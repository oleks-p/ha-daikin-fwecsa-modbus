"""The entity set: ids, values, and what is enabled on this unit."""

from __future__ import annotations

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.daikin_fwecsa_modbus.const import DOMAIN


async def test_entity_ids_carry_the_prefix(hass, setup_integration):
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, setup_integration.entry_id)
    prefix = f"{setup_integration.entry_id}_"
    for entry in entries:
        key = entry.unique_id.removeprefix(prefix)
        expected = "climate.fancoil" if key == "fancoil" else f"{entry.domain}.fancoil_{key}"
        assert entry.entity_id == expected


async def test_read_only_by_default(hass, setup_integration):
    registry = er.async_get(hass)
    domains = {e.domain for e in er.async_entries_for_config_entry(
        registry, setup_integration.entry_id)}
    assert domains == {"sensor", "binary_sensor", "climate"}
    climate = hass.states.get("climate.fancoil")
    assert climate.attributes["supported_features"] == 0
    assert climate.attributes["hvac_modes"] == ["heat"]


async def test_writes_on_adds_the_writable_platforms(hass, writes_on, setup_integration):
    registry = er.async_get(hass)
    entries = er.async_entries_for_config_entry(registry, setup_integration.entry_id)
    by_domain: dict[str, int] = {}
    for entry in entries:
        by_domain[entry.domain] = by_domain.get(entry.domain, 0) + 1
    # Sensors: 15 input, 12 holding, 2 for the mode, 2 for the link. Binary sensors:
    # 30 inputs and 17 coils; the mode is neither, it is the 2 sensors and a select.
    assert by_domain == {"sensor": 31, "binary_sensor": 47, "switch": 17, "number": 11,
                         "select": 2, "climate": 1}


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.fancoil_room_temperature", "23.0"),
        ("sensor.fancoil_water_temperature", "29.0"),
        ("sensor.fancoil_single_setpoint", "23.0"),
        ("sensor.fancoil_active_setpoint", "23.0"),
        ("sensor.fancoil_cooling_setpoint", "24.0"),
        ("sensor.fancoil_heating_setpoint_max", "30.0"),
        ("sensor.fancoil_fan_speed", "auto"),
        ("sensor.fancoil_fan_status", "off"),
        ("sensor.fancoil_valve_type", "on_off"),
        ("binary_sensor.fancoil_unit_on", "on"),
        ("sensor.fancoil_mode_in_use", "heating"),
        ("sensor.fancoil_mode", "heating"),
        ("binary_sensor.fancoil_alarm", "off"),
        ("binary_sensor.fancoil_valve_open", "off"),
        ("binary_sensor.fancoil_water_probe_present", "on"),
        ("binary_sensor.fancoil_power", "on"),
        ("binary_sensor.fancoil_master_setpoint", "on"),
    ],
)
async def test_values(hass, setup_integration, entity_id, expected):
    assert hass.states.get(entity_id).state == expected


async def test_parts_the_unit_lacks_start_disabled(hass, setup_integration):
    registry = er.async_get(hass)
    for entity_id in ("sensor.fancoil_room_humidity", "sensor.fancoil_hot_water_temperature",
                      "sensor.fancoil_modulating_fan_output", "sensor.fancoil_analog_output_1",
                      "binary_sensor.fancoil_heater_on"):
        assert registry.async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
        assert hass.states.get(entity_id) is None
    assert registry.async_get("sensor.fancoil_water_temperature").disabled_by is None


async def test_retired_entities_are_removed(hass, config_entry, modbus_clients, freezer):
    # 0.1.1 made these; 0.1.2 named them anew, as the mode select and sensors.
    registry = er.async_get(hass)
    retired = [("switch", "winter_mode"), ("binary_sensor", "winter"),
               ("binary_sensor", "winter_mode"), ("switch", "master_winter_mode")]
    for domain, key in retired:
        registry.async_get_or_create(domain, DOMAIN, f"{config_entry.entry_id}_{key}",
                                     config_entry=config_entry,
                                     suggested_object_id=f"fancoil_{key}")
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    for domain, key in retired:
        assert registry.async_get(f"{domain}.fancoil_{key}") is None
    assert hass.states.get("sensor.fancoil_mode_in_use").state == "heating"


#: What Home Assistant's Security view lists from binary sensors, besides
#: diagnostic tamper sensors (frontend 2026.10).
SECURITY_CLASSES = {"lock", "door", "window", "garage_door", "opening", "carbon_monoxide",
                    "gas", "glass_break", "moisture", "safety", "smoke", "tamper"}


async def test_nothing_is_listed_as_security(hass, writes_on, setup_integration):
    # The valve was an "opening", so the Security view showed it beside the doors.
    for state in hass.states.async_all("binary_sensor"):
        assert state.attributes.get("device_class") not in SECURITY_CLASSES, state.entity_id


async def test_device(hass, setup_integration):
    device = dr.async_get(hass).async_get_device(
        identifiers={(DOMAIN, setup_integration.entry_id)})
    assert (device.manufacturer, device.model, device.name) == ("Daikin", "FWECSA", "Fancoil")


async def test_switching_writes_off_removes_the_writable_entities(hass, writes_on,
                                                                  setup_integration):
    registry = er.async_get(hass)
    assert registry.async_get("switch.fancoil_power") is not None
    hass.config_entries.async_update_entry(setup_integration, options={})
    await hass.config_entries.async_reload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert registry.async_get("switch.fancoil_power") is None
    assert registry.async_get("number.fancoil_heating_setpoint") is None
    assert hass.states.get("sensor.fancoil_heating_setpoint").state == "21.0"
