"""Shared entity base for the FWECSA integration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import EntityDescription
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_ENTITY_PREFIX,
    DEFAULT_ENTITY_PREFIX,
    DEFAULT_NAME,
    DOMAIN,
    MANUFACTURER,
    MODEL,
)
from .coordinator import FwecsaCoordinator


@dataclass(frozen=True, kw_only=True)
class FwecsaEntityDescription(EntityDescription):
    """Where an entity's value comes from, and which units it belongs on."""

    value_fn: Callable[[FwecsaCoordinator], Any]
    #: A model.UnitConfig feature. Every register gets its entity, but one for a
    #: part the unit reports it does not have (a humidity probe, a 4-pipe hot
    #: water circuit) starts disabled: it would only ever read nonsense or zero.
    feature: str | None = None
    attrs_fn: Callable[[FwecsaCoordinator], dict[str, Any]] | None = None


def value(key: str) -> Callable[[FwecsaCoordinator], Any]:
    return lambda coordinator: coordinator.data.values.get(key)


class FwecsaEntity(CoordinatorEntity[FwecsaCoordinator]):
    """Wires every entity to the one device and the shared coordinator."""

    _attr_has_entity_name = True
    entity_description: FwecsaEntityDescription

    def __init__(self, coordinator: FwecsaCoordinator, description: FwecsaEntityDescription,
                 domain: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self.entity_description = description
        self._attr_translation_key = description.translation_key or description.key
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        # A suggested entity id is used as it stands on first registration, so
        # the ids are <domain>.<prefix>_<key> whatever the device is named.
        prefix = entry.data.get(CONF_ENTITY_PREFIX, DEFAULT_ENTITY_PREFIX)
        self.entity_id = f"{domain}.{prefix}_{description.key}"
        if description.feature and description.feature not in coordinator.unit.features:
            self._attr_entity_registry_enabled_default = False
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            name=DEFAULT_NAME,
            model=MODEL,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        attrs_fn = self.entity_description.attrs_fn
        return attrs_fn(self.coordinator) if attrs_fn else None


def remove_stale(hass, entry, domain: str) -> None:
    """Drop this entry's leftover entities of one domain from the registry.

    Used for the writable platforms when writes are switched off: their
    entities are not created, and a number or switch has no history worth
    keeping, so a left-over registry entry would only sit there unavailable.
    """
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    for item in er.async_entries_for_config_entry(registry, entry.entry_id):
        if item.domain == domain:
            registry.async_remove(item.entity_id)
