"""Diagnostics: raw values alongside the decoded view, for bug reports.

The raw values matter most: they let a decoding problem be reproduced against
the simulator without access to the unit.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST
from homeassistant.core import HomeAssistant

from . import FwecsaConfigEntry
from .block_planner import describe
from .const import CONF_SERIAL_PORT
from .registers import REGISTER_MAP_VERSION

TO_REDACT = {CONF_HOST, CONF_SERIAL_PORT}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: FwecsaConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data.coordinator
    data = coordinator.data
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": dict(entry.options),
        },
        "unit": {**coordinator.unit.as_dict(), "register_map": REGISTER_MAP_VERSION},
        "link": coordinator.link_stats(),
        "writes": {
            "allowed": coordinator.writes.allowed,
            "switching": coordinator.switching,
            "recent_writes": list(coordinator.writes.log),
        },
        "block_plan": describe(coordinator.blocks),
        "stale": data.stale,
        "values": dict(sorted(data.values.items())),
        "raw": dict(sorted(data.raw.items())),
    }
