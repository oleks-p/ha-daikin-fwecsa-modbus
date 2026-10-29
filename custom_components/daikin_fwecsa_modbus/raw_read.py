"""The read_registers action: raw values from any table, for research and support.

The manual's tables are short and say little about encoding. This reads
through the integration's own bus, so a question about the unit can be
answered without stopping the integration or putting a second master on the
bus. Only reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError

from .const import DOMAIN
from .registers import TABLE_SIZES, Table
from .transport import FwecsaIllegalError, FwecsaTransientError

if TYPE_CHECKING:
    from .coordinator import FwecsaCoordinator


async def async_read(coordinator: FwecsaCoordinator, table: str, address: int | None,
                     count: int) -> dict[str, Any]:
    """Read ``count`` values from ``address``, or the whole documented table."""
    which = Table(table)
    if address is None:
        address, count = 0, TABLE_SIZES[which]
    try:
        values = await coordinator.bus.read(coordinator.slave, which, address, count)
    except FwecsaIllegalError as err:
        return {"table": str(which), "address": address, "count": count, "refused": err.code}
    except FwecsaTransientError as err:
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="read_failed",
                                 translation_placeholders={"error": str(err)}) from err
    return {"table": str(which), "address": address, "count": count,
            "values": {str(address + i): v for i, v in enumerate(values)}}
