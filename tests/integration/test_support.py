"""Translations, diagnostics and the read_registers action."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from homeassistant.exceptions import ServiceValidationError
from pytest_homeassistant_custom_component.components.diagnostics import (
    get_diagnostics_for_config_entry,
)

from custom_components.daikin_fwecsa_modbus.binary_sensor import BINARY_SENSORS
from custom_components.daikin_fwecsa_modbus.const import DOMAIN
from custom_components.daikin_fwecsa_modbus.number import NUMBERS
from custom_components.daikin_fwecsa_modbus.select import SELECTS
from custom_components.daikin_fwecsa_modbus.sensor import SENSORS
from custom_components.daikin_fwecsa_modbus.switch import SWITCHES

ROOT = Path(__file__).parents[2]
STRINGS = ROOT / "custom_components" / DOMAIN / "strings.json"


@pytest.mark.parametrize("tool", ["gen_translations.py", "gen_docs.py"])
def test_generated_files_are_current(tool):
    result = subprocess.run([sys.executable, f"tools/{tool}", "--check"],
                            cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize(("platform", "descriptions"), [
    ("sensor", SENSORS), ("binary_sensor", BINARY_SENSORS), ("switch", SWITCHES),
    ("number", NUMBERS), ("select", SELECTS),
])
def test_every_entity_has_a_name(platform, descriptions):
    names = json.loads(STRINGS.read_text(encoding="utf-8"))["entity"][platform]
    keys = {d.translation_key or d.key for d in descriptions}
    assert keys == set(names)
    for description in descriptions:
        states = names[description.key].get("state")
        if getattr(description, "options", None):
            assert set(description.options) == set(states)


async def test_diagnostics(hass, hass_client, setup_integration):
    diagnostics = await get_diagnostics_for_config_entry(hass, hass_client, setup_integration)
    assert diagnostics["entry"]["data"]["host"] == "**REDACTED**"
    assert diagnostics["unit"]["features"] == ["step_fan", "valve", "valve_present",
                                               "water_probe_present"]
    assert diagnostics["raw"]["input:0+15"][0] == 230
    assert diagnostics["values"]["room_temperature"] == 23.0


async def test_read_registers(hass, setup_integration):
    result = await hass.services.async_call(DOMAIN, "read_registers",
                                            {"table": "input", "address": 0, "count": 3},
                                            blocking=True, return_response=True)
    assert result["values"] == {"0": 230, "1": 0, "2": 290}
    result = await hass.services.async_call(DOMAIN, "read_registers", {"table": "coil"},
                                            blocking=True, return_response=True)
    assert len(result["values"]) == 18
    result = await hass.services.async_call(DOMAIN, "read_registers",
                                            {"table": "holding", "address": 12},
                                            blocking=True, return_response=True)
    assert result["refused"] == 2


async def test_read_registers_needs_one_entry(hass, setup_integration):
    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "read_registers",
                                       {"table": "input", "config_entry_id": "nope"},
                                       blocking=True, return_response=True)
