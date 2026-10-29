"""Config, reconfigure and options flows."""

from __future__ import annotations

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType

from custom_components.daikin_fwecsa_modbus.const import (
    CONF_ALLOW_WRITES,
    CONF_SWITCHING,
    CONF_UNAVAILABLE_AFTER,
    DOMAIN,
)

NETWORK = {"host": "127.0.0.1", "port": 10502, "transport": "tcp", "slave": 1,
           "entity_prefix": "fancoil"}


async def _network_form(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.MENU
    return await hass.config_entries.flow.async_configure(result["flow_id"],
                                                          {"next_step_id": "network"})


async def test_network(hass, fake, modbus_clients):
    result = await _network_form(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], NETWORK)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "FWECSA 1 (3 speeds, 2 pipes, valve on/off)"
    assert result["data"] == NETWORK
    assert result["result"].unique_id == "tcp:127.0.0.1:10502#1"


async def test_errors(hass, fake, modbus_clients):
    result = await _network_form(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**NETWORK, "slave": 9})
    assert result["errors"] == {"base": "cannot_connect"}
    fake.tables["input"][4] = 9
    result = await hass.config_entries.flow.async_configure(result["flow_id"], NETWORK)
    assert result["errors"] == {"base": "not_fwecsa"}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**NETWORK, "entity_prefix": "Fan Coil"})
    assert result["errors"] == {"entity_prefix": "invalid_prefix"}


async def test_already_configured(hass, config_entry, fake, modbus_clients):
    result = await _network_form(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**NETWORK, "entity_prefix": "other"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_reconfigure_to_serial(hass, setup_integration, fake, modbus_clients):
    result = await setup_integration.start_reconfigure_flow(hass)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"next_step_id": "reconfigure_serial"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"serial_port": "/dev/ttyUSB0", "baudrate": "9600", "slave": 1})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    data = setup_integration.data
    assert data["transport"] == "serial" and data["baudrate"] == 9600
    assert "host" not in data and data["entity_prefix"] == "fancoil"
    assert setup_integration.unique_id == "serial:/dev/ttyUSB0#1"


async def test_options(hass, setup_integration):
    result = await hass.config_entries.options.async_init(setup_integration.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_UNAVAILABLE_AFTER: 120, CONF_ALLOW_WRITES: True, CONF_SWITCHING: "auto_water"})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()
    assert setup_integration.options == {CONF_UNAVAILABLE_AFTER: 120, CONF_ALLOW_WRITES: True,
                                         CONF_SWITCHING: "auto_water"}
    assert hass.states.get("switch.fancoil_power") is not None
    assert hass.states.get("climate.fancoil").state == "auto"
