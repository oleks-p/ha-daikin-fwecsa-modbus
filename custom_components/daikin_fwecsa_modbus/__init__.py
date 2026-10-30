"""The Daikin FWECSA integration (Modbus RTU).

The FWECSA is the controller in Daikin's FWB/FWV/FWL hydronic fancoils. This
reads all four of its Modbus tables. Writes are opt-in per entry ("allow
writes"), one value at a time, each read back -- see writes.py. The unit's own
controller still runs the fan and the valve.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady, ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey

from .const import CONF_SLAVE, DOMAIN, PLATFORMS, SERVICE_READ_REGISTERS
from .coordinator import FwecsaCoordinator
from .model import NotAnFwecsa, async_identify
from .raw_read import async_read
from .registers import Table
from .transport import BusRegistry, Endpoint, FwecsaBus, FwecsaTransientError

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

READ_REGISTERS_SCHEMA = vol.Schema({
    vol.Optional("config_entry_id"): cv.string,
    vol.Required("table"): vol.In([str(t) for t in Table]),
    vol.Optional("address"): vol.All(vol.Coerce(int), vol.Range(min=0, max=0xFFFF)),
    vol.Optional("count", default=1): vol.All(vol.Coerce(int), vol.Range(min=1, max=125)),
})

#: One bus per physical link, shared by every entry and config flow using it.
BUSES: HassKey[BusRegistry] = HassKey(DOMAIN)


@dataclass
class FwecsaRuntime:
    endpoint: Endpoint
    bus: FwecsaBus
    coordinator: FwecsaCoordinator


FwecsaConfigEntry = ConfigEntry[FwecsaRuntime]


def bus_registry(hass: HomeAssistant) -> BusRegistry:
    return hass.data.setdefault(BUSES, BusRegistry())


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the admin action, once, for every entry to use."""

    async def read_registers(call: ServiceCall) -> ServiceResponse:
        entry = _target_entry(hass, call.data.get("config_entry_id"))
        return await async_read(entry.runtime_data.coordinator, call.data["table"],
                                call.data.get("address"), call.data["count"])

    # Admin only: it only reads, but at any address and without the map.
    async_register_admin_service(hass, DOMAIN, SERVICE_READ_REGISTERS, read_registers,
                                 schema=READ_REGISTERS_SCHEMA,
                                 supports_response=SupportsResponse.ONLY)
    return True


def _target_entry(hass: HomeAssistant, entry_id: str | None) -> FwecsaConfigEntry:
    loaded = [e for e in hass.config_entries.async_entries(DOMAIN)
              if e.state is ConfigEntryState.LOADED]
    if entry_id:
        loaded = [e for e in loaded if e.entry_id == entry_id]
    if len(loaded) != 1:
        raise ServiceValidationError(translation_domain=DOMAIN, translation_key="choose_entry")
    return loaded[0]


#: Entity keys 0.1.2 retired: the winter switch and inputs became the mode select
#: and sensors, under new ids. Left in the registry, they would sit unavailable.
RETIRED_KEYS = ("winter", "winter_mode", "master_winter_mode")


def _remove_retired(hass: HomeAssistant, entry: FwecsaConfigEntry) -> None:
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_"
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.unique_id.removeprefix(prefix) in RETIRED_KEYS:
            registry.async_remove(item.entity_id)


async def async_setup_entry(hass: HomeAssistant, entry: FwecsaConfigEntry) -> bool:
    """Read the unit's configuration, then start polling it."""
    endpoint = Endpoint.from_config(entry.data)
    registry = bus_registry(hass)
    bus = registry.acquire(endpoint)
    slave = entry.data[CONF_SLAVE]
    try:
        unit = await async_identify(bus, slave)
    except NotAnFwecsa as err:
        await registry.release(endpoint)
        raise ConfigEntryError(translation_domain=DOMAIN, translation_key="not_fwecsa",
                               translation_placeholders={"slave": str(slave)}) from err
    except FwecsaTransientError as err:
        await registry.release(endpoint)
        raise ConfigEntryNotReady(translation_domain=DOMAIN, translation_key="cannot_connect",
                                  translation_placeholders={"endpoint": str(endpoint)}) from err

    coordinator = FwecsaCoordinator(hass, entry, bus, slave, unit)
    try:
        await coordinator.async_config_entry_first_refresh()
    except ConfigEntryNotReady:
        await registry.release(endpoint)
        raise
    entry.runtime_data = FwecsaRuntime(endpoint, bus, coordinator)
    _remove_retired(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: FwecsaConfigEntry) -> bool:
    """Stop polling and let the bus go if nothing else uses it."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await bus_registry(hass).release(entry.runtime_data.endpoint)
    return unloaded
