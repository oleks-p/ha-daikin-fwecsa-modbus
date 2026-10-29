"""Polling coordinator: reads the four tables and decodes them."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .block_planner import Block, plan_blocks, split
from .const import (
    CONF_SWITCHING,
    CONF_UNAVAILABLE_AFTER,
    DEFAULT_SWITCHING,
    DEFAULT_UNAVAILABLE_AFTER,
    DOMAIN,
    POLL_INTERVAL,
)
from .model import UnitConfig
from .registers import REGISTERS, Reg, Table
from .transport import FwecsaBus, FwecsaIllegalError, FwecsaTransientError
from .writes import WriteGate

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)


def decode(reg: Reg, raw: int) -> float | int | bool | None:
    """One raw value -> the register's value, or None if insane."""
    if reg.table.bits:
        return bool(raw)
    value: float | int = raw - 0x10000 if reg.signed and raw & 0x8000 else raw
    if reg.scale != 1.0:
        value = round(value * reg.scale, 3)
    if reg.sane and not reg.sane[0] <= value <= reg.sane[1]:
        return None
    return value


@dataclass
class FwecsaData:
    """One poll's worth of decoded state."""

    values: dict[str, Any] = field(default_factory=dict)
    #: Raw values per block key, for diagnostics.
    raw: dict[str, list[int]] = field(default_factory=dict)
    #: True when this cycle's reads failed and the values are the last good ones.
    stale: bool = False

    def get(self, key: str, default: Any = None) -> Any:
        return self.values.get(key, default)


class FwecsaCoordinator(DataUpdateCoordinator[FwecsaData]):
    """Reads the FWECSA and decodes the register map."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        bus: FwecsaBus,
        slave: int,
        unit: UnitConfig,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {slave}",
            update_interval=timedelta(seconds=POLL_INTERVAL),
        )
        self.bus = bus
        self.slave = slave
        self.unit = unit
        self.switching: str = entry.options.get(CONF_SWITCHING, DEFAULT_SWITCHING)
        self.unavailable_after = float(
            entry.options.get(CONF_UNAVAILABLE_AFTER, DEFAULT_UNAVAILABLE_AFTER))
        self.registers = REGISTERS
        self.blocks: list[Block] = list(plan_blocks(self.registers))
        self._cache: dict[str, list[int]] = {}
        self._rejected: set[str] = set()
        # Link health, surfaced as diagnostic entities and in diagnostics.
        self.last_success: float | None = None
        self.last_success_at: datetime | None = None
        self.consecutive_failures = 0
        self.read_failures = 0
        self.split_blocks: list[str] = []
        self.data = FwecsaData()
        self.writes = WriteGate(self)

    # -- polling ---------------------------------------------------------

    async def _async_update_data(self) -> FwecsaData:
        now = time.monotonic()
        try:
            for block in list(self.blocks):
                await self._fetch(block)
        except FwecsaTransientError as err:
            self.consecutive_failures += 1
            self.read_failures += 1
            # Keep showing the last good values until the outage has lasted
            # `unavailable_after`: one lost frame must not flap every entity.
            if self.last_success is None or now - self.last_success > self.unavailable_after:
                raise UpdateFailed(f"No answer from the FWECSA: {err}") from err
            _LOGGER.debug("Read failed (%s); keeping the last values", err)
            data = self._build()
            data.stale = True
            return data
        self.last_success = now
        self.last_success_at = dt_util.utcnow()
        self.consecutive_failures = 0
        return self._build()

    async def _fetch(self, block: Block) -> None:
        try:
            words = await self.bus.read(self.slave, block.table, block.address, block.count)
        except FwecsaIllegalError as err:
            if block.count > 1:
                self._split(block, err)
                for single in split(block):
                    await self._fetch(single)
                return
            # One value the unit does not have: show it as unknown, keep going.
            if block.key not in self._rejected:
                self._rejected.add(block.key)
                _LOGGER.warning("The FWECSA does not answer %s %s (%s); it will show as "
                                "unknown", block.table, block.registers[0].key, err)
            self._cache.pop(block.key, None)
            return
        self._cache[block.key] = words

    def _split(self, block: Block, err: Exception) -> None:
        """Replace a rejected block with one read per value, for good."""
        _LOGGER.warning("The FWECSA refused the read %s (%s); reading those values one at a "
                        "time from now on", block, err)
        index = self.blocks.index(block)
        self.blocks[index:index + 1] = split(block)
        self.split_blocks.append(str(block))
        self._cache.pop(block.key, None)

    # -- decoding --------------------------------------------------------

    def _build(self) -> FwecsaData:
        values: dict[str, Any] = {}
        for block in self.blocks:
            words = self._cache.get(block.key)
            if words is None:
                continue
            for reg in block.registers:
                values[reg.key] = decode(reg, words[reg.address - block.address])
        return FwecsaData(values=values,
                          raw={key: list(words) for key, words in self._cache.items()})

    def patch_register(self, table: Table, address: int, raw: int) -> None:
        """Fold a value just read back after a write into the cache, and publish."""
        for block in self.blocks:
            words = self._cache.get(block.key)
            if words is not None and block.table is table and block.address <= address <= block.end:
                words[address - block.address] = raw
        self.async_set_updated_data(self._build())

    # -- diagnostics -----------------------------------------------------

    def link_stats(self) -> dict[str, Any]:
        return {
            "last_success": self.last_success_at.isoformat() if self.last_success_at else None,
            "consecutive_failures": self.consecutive_failures,
            "read_failures": self.read_failures,
            "requests": self.bus.requests,
            "bus_failures": self.bus.failures,
            "last_error": self.bus.last_error,
            "split_blocks": list(self.split_blocks),
            "rejected_registers": sorted(self._rejected),
        }
