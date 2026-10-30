"""The integration against a probe capture of the reference unit (2026-10-30).

The other tests run on a synthetic unit built to exercise the code: three fan
speeds, keyboard switching, every consent on. The reference unit is none of
those, so these tests run it as tools/probe_fwecsa.py found it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from homeassistant.components.climate import ATTR_HVAC_ACTION, HVACAction, HVACMode
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.helpers import entity_registry as er

from custom_components.daikin_fwecsa_modbus.const import CONF_SWITCHING
from tests.sim import FakeFwecsa

CAPTURE = Path(__file__).parents[1] / "fixtures" / "fwecsa_capture.json"


@pytest.fixture
def fake() -> FakeFwecsa:
    fake = FakeFwecsa.from_fixture(CAPTURE, auto_switching=True)
    yield fake
    assert fake.writes == []


@pytest.fixture
def on_water(hass, config_entry):
    """Read-only, with the switching the unit is set to."""
    hass.config_entries.async_update_entry(config_entry, options={CONF_SWITCHING: "auto_water"})
    return config_entry


def test_a_table_read_whole_reads_as_its_values_one_by_one():
    capture = json.loads(CAPTURE.read_text(encoding="utf-8"))
    for table, block in capture["block"].items():
        assert [single["values"][0] for single in capture["single"][table]] == block["values"]
        # The unit answers past its documented end, with zeros: the table
        # sizes come from the manual, not from where reads start to fail.
        assert capture["past_end"][table]["values"] == [0]


def test_the_simulator_reproduces_the_capture(fake):
    # Its controller model (status follows command, setpoints held to their
    # limits, the season left to the water) settles on what the unit reported.
    captured = json.loads(CAPTURE.read_text(encoding="utf-8"))["tables"]
    fake.follow()
    assert fake.tables == captured


async def test_identified(hass, on_water, setup_integration):
    unit = setup_integration.runtime_data.coordinator.unit
    assert unit.summary == "4 speeds, 2 pipes, valve on/off"


async def test_climate(hass, auto_switching, setup_integration):
    state = hass.states.get("climate.fancoil")
    assert state.state == HVACMode.AUTO
    assert state.attributes["hvac_modes"] == [HVACMode.OFF, HVACMode.AUTO]
    assert state.attributes["current_temperature"] == 23.0
    assert state.attributes[ATTR_TEMPERATURE] == 23.0          # the single setpoint
    assert state.attributes[ATTR_HVAC_ACTION] == HVACAction.IDLE
    assert state.attributes["fan_mode"] == "auto"
    assert state.attributes["fan_modes"] == ["extra_low", "low", "medium", "high", "auto"]


@pytest.mark.parametrize(
    ("entity_id", "expected"),
    [
        ("sensor.fancoil_water_temperature", "28.3"),
        ("sensor.fancoil_heating_setpoint", "24.0"),
        ("sensor.fancoil_single_setpoint", "23.0"),
        # Holding 0 holds 0xDC00: shown as unknown, not as -921.6 °C ...
        ("sensor.fancoil_cooling_setpoint", "unknown"),
        # ... while the unit uses its lower limit in its place.
        ("sensor.fancoil_cooling_setpoint_status", "10.0"),
        # The water decides the season: the unit heats, the coil says summer.
        ("sensor.fancoil_mode_in_use", "heating"),
        ("sensor.fancoil_mode", "cooling"),
        ("binary_sensor.fancoil_master_setpoint", "off"),
        ("binary_sensor.fancoil_fan_auto_mode", "on"),
        ("sensor.fancoil_fan_speed", "auto"),
        ("sensor.fancoil_valve_type", "on_off"),
    ],
)
async def test_values(hass, on_water, setup_integration, entity_id, expected):
    assert hass.states.get(entity_id).state == expected


async def test_parts_the_unit_lacks_start_disabled(hass, on_water, setup_integration):
    registry = er.async_get(hass)
    for entity_id in ("sensor.fancoil_room_humidity", "sensor.fancoil_hot_water_temperature",
                      "sensor.fancoil_modulating_fan_output", "binary_sensor.fancoil_heater_on"):
        assert registry.async_get(entity_id).disabled_by is er.RegistryEntryDisabler.INTEGRATION
