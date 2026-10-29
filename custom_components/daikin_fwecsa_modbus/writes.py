"""Opt-in writes: one coil or holding register at a time, read back.

Nothing here runs unless the entry's "allow writes" option is on. Even then a
value is written only when all of these hold:

1. it has a WriteSpec (registers.WRITE_SPECS): a coil or a holding register;
2. the value is in range and on the step;
3. it differs from what the unit holds now -- read fresh, not from the cache,
   so nothing is written just to say the same thing again;
4. the rate limits allow it.

Every write is read back. A value the unit acknowledges but does not keep is
reported as an error, naming the consent coil the function depends on when that
coil is off: the FWECSA takes a function from Modbus only with its "enable ...
from MASTER" coil on, and otherwise ignores the write without an exception.

Unlike a heat pump's service parameters, every variable here is one the manual
offers a supervisor to write, so there is no per-register write check before
the first write; the read-back is the check, every time.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import TYPE_CHECKING, Any

from homeassistant.core import Context
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ALLOW_WRITES,
    DOMAIN,
    EVENT_WRITTEN,
    WRITE_DAILY_LIMIT,
    WRITE_MIN_INTERVAL,
)
from .registers import BY_KEY, CONSENT, WRITE_SPECS, Reg, Table, WriteSpec
from .transport import FwecsaIllegalError, FwecsaTransientError

if TYPE_CHECKING:
    from .coordinator import FwecsaCoordinator


def encode(reg: Reg, value: float) -> int:
    if reg.table is Table.COIL:
        return 1 if value else 0
    raw = round(value / reg.scale)
    return raw & 0xFFFF if reg.signed else raw


def decode(reg: Reg, raw: int) -> float | int:
    if reg.table is Table.COIL:
        return raw
    value = raw - 0x10000 if reg.signed and raw & 0x8000 else raw
    return round(value * reg.scale, 3) if reg.scale != 1.0 else value


def on_step(spec: WriteSpec, value: float) -> bool:
    steps = (value - spec.minimum) / spec.step
    return spec.minimum <= value <= spec.maximum and abs(steps - round(steps)) < 1e-6


class WriteGate:
    """What may be written on one unit, and the write path itself."""

    def __init__(self, coordinator: FwecsaCoordinator) -> None:
        self.coordinator = coordinator
        self.allowed = bool(coordinator.config_entry.options.get(CONF_ALLOW_WRITES, False))
        self.log: deque[dict[str, Any]] = deque(maxlen=20)
        self._last_write: dict[str, float] = {}
        self._recent: deque[float] = deque()
        # A write is three bus exchanges (read, write, read back); the bus lock
        # keeps the exchanges apart, this keeps the sequences apart.
        self._lock = asyncio.Lock()

    def writable(self, key: str) -> bool:
        return self.allowed and key in WRITE_SPECS

    async def async_write(self, key: str, value: float, context: Context | None = None) -> None:
        if not self.allowed:
            raise ServiceValidationError(translation_domain=DOMAIN,
                                         translation_key="writes_disabled")
        if key not in WRITE_SPECS:
            raise ServiceValidationError(translation_domain=DOMAIN,
                                         translation_key="not_writable",
                                         translation_placeholders={"key": key})
        spec, reg = WRITE_SPECS[key], BY_KEY[key]
        if not on_step(spec, value):
            raise ServiceValidationError(
                translation_domain=DOMAIN, translation_key="out_of_range",
                translation_placeholders={"key": key, "value": str(value),
                                          "minimum": str(spec.minimum),
                                          "maximum": str(spec.maximum), "step": str(spec.step)})
        raw = encode(reg, value)
        async with self._lock:
            before = await self._read(reg)
            if before == raw:
                self.coordinator.patch_register(reg.table, reg.address, before)
                return  # already so: no write, no wear
            self._rate_limit(key)
            await self._send(reg, raw)
            after = await self._read(reg)
            self._note(key, reg, before, raw, after, context)
        if after != raw:
            self._not_applied(key, reg, value, after)

    def _not_applied(self, key: str, reg: Reg, value: float, after: int) -> None:
        placeholders = {"key": key, "expected": str(value), "actual": str(decode(reg, after))}
        consent = CONSENT.get(key)
        if consent and self.coordinator.data.values.get(consent) is False:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="write_not_applied_consent",
                translation_placeholders={**placeholders, "consent": consent})
        raise HomeAssistantError(translation_domain=DOMAIN, translation_key="write_not_applied",
                                 translation_placeholders=placeholders)

    def _rate_limit(self, key: str) -> None:
        now = time.monotonic()
        while self._recent and now - self._recent[0] > 86400:
            self._recent.popleft()
        if (now - self._last_write.get(key, float("-inf")) < WRITE_MIN_INTERVAL
                or len(self._recent) >= WRITE_DAILY_LIMIT):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="rate_limited",
                translation_placeholders={"key": key, "interval": str(int(WRITE_MIN_INTERVAL)),
                                          "daily": str(WRITE_DAILY_LIMIT)})
        self._last_write[key] = now
        self._recent.append(now)

    async def _read(self, reg: Reg) -> int:
        coordinator = self.coordinator
        try:
            (raw,) = await coordinator.bus.read(coordinator.slave, reg.table, reg.address, 1)
        except (FwecsaTransientError, FwecsaIllegalError) as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="write_failed",
                                     translation_placeholders={"error": str(err)}) from err
        return raw

    async def _send(self, reg: Reg, raw: int) -> None:
        coordinator = self.coordinator
        try:
            await coordinator.bus.write(coordinator.slave, reg.table, reg.address, raw)
        except FwecsaIllegalError as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="write_refused",
                                     translation_placeholders={"code": str(err.code)}) from err
        except FwecsaTransientError as err:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="write_failed",
                                     translation_placeholders={"error": str(err)}) from err

    def _note(self, key: str, reg: Reg, before: int, raw: int, after: int,
              context: Context | None) -> None:
        coordinator = self.coordinator
        coordinator.patch_register(reg.table, reg.address, after)
        record = {"at": dt_util.utcnow().isoformat(), "key": key, "table": str(reg.table),
                  "address": reg.address, "old": decode(reg, before), "new": decode(reg, raw),
                  "read_back": decode(reg, after), "applied": after == raw}
        self.log.append(record)
        coordinator.hass.bus.async_fire(
            EVENT_WRITTEN, {**record, "entry_id": coordinator.config_entry.entry_id},
            context=context)
