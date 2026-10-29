"""The RS-485 link: one serialised Modbus master per physical connection.

The bus has exactly one master. Everything that talks to a given serial port or
gateway goes through one ``FwecsaBus``, and every request takes its lock. Two
config entries for two fancoils on the same pair of wires share one bus through
``BusRegistry``, so they queue rather than collide. A bus shared with other
integrations (a heat pump, a wall panel) needs a gateway such as mbusd in front
of it: a serial port opens once.

Two kinds of failure are kept apart, because they call for opposite responses:

* ``FwecsaTransientError``: the link let us down (timeout, no reply, a closed
  socket, a gateway answering "target failed to respond"). Nothing is wrong
  with the request; try again later. The client is dropped so the next request
  starts from a clean, flushed connection.
* ``FwecsaIllegalError``: the unit answered and refused the request (Modbus
  exception 1, 2 or 3). Retrying will not help; the caller must change it.

Writes use FC15 (coils) and FC16 (holding registers) and nothing else: the
FWECSA lists only the multiple-write forms, and does not reply to FC5 or FC6.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pymodbus import FramerType
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient

from .const import (
    CONF_BAUDRATE,
    CONF_SERIAL_PORT,
    CONF_TRANSPORT,
    DEFAULT_BAUDRATE,
    DEFAULT_TCP_PORT,
    FRAME_GAP,
    REQUEST_TIMEOUT,
    RESYNC_DELAY,
    TRANSPORT_RTU_OVER_TCP,
    TRANSPORT_SERIAL,
    TRANSPORT_TCP,
)
from .registers import Table

_LOGGER = logging.getLogger(__name__)

#: Exception codes that mean "this request is wrong", not "the link is bad".
ILLEGAL_CODES = frozenset({1, 2, 3})

READS = {
    Table.COIL: "read_coils",
    Table.DISCRETE: "read_discrete_inputs",
    Table.HOLDING: "read_holding_registers",
    Table.INPUT: "read_input_registers",
}


class FwecsaError(Exception):
    """Base for link and protocol errors."""


class FwecsaTransientError(FwecsaError):
    """The link failed; the same request may well succeed later."""


class FwecsaIllegalError(FwecsaError):
    """The unit refused the request with a Modbus exception."""

    def __init__(self, table: Table, address: int, count: int, code: int, *,
                 write: int | None = None) -> None:
        what = (f"read {table} {address}+{count}" if write is None
                else f"write {table} {address}={write}")
        super().__init__(f"{what} refused with exception {code}")
        self.table, self.address, self.count, self.code = table, address, count, code


@dataclass(frozen=True, slots=True)
class Endpoint:
    """Where the bus is: a local serial port, or a host and port."""

    transport: str
    serial_port: str | None = None
    baudrate: int = DEFAULT_BAUDRATE
    host: str | None = None
    port: int = DEFAULT_TCP_PORT

    @classmethod
    def from_config(cls, data: Mapping[str, Any]) -> Endpoint:
        transport = data[CONF_TRANSPORT]
        if transport == TRANSPORT_SERIAL:
            return cls(transport, serial_port=data[CONF_SERIAL_PORT],
                       baudrate=int(data.get(CONF_BAUDRATE, DEFAULT_BAUDRATE)))
        return cls(transport, host=data["host"], port=int(data.get("port", DEFAULT_TCP_PORT)))

    @property
    def key(self) -> str:
        """Identity of the physical link: two entries on one key share a bus."""
        if self.transport == TRANSPORT_SERIAL:
            return f"serial:{self.serial_port}"
        return f"tcp:{self.host}:{self.port}"

    def __str__(self) -> str:
        if self.transport == TRANSPORT_SERIAL:
            return f"{self.serial_port} @ {self.baudrate} 8N1"
        framing = "RTU over TCP" if self.transport == TRANSPORT_RTU_OVER_TCP else "Modbus TCP"
        return f"{self.host}:{self.port} ({framing})"

    def make_client(self, timeout: float) -> Any:
        # retries=0: one attempt per request -- the coordinator's polling is the
        # retry. reconnect_delay=0: no background reconnect loop, which would
        # otherwise hold the port open from a client that has been abandoned.
        common = {"timeout": timeout, "retries": 0,
                  "reconnect_delay": 0, "reconnect_delay_max": 0}
        if self.transport == TRANSPORT_SERIAL:
            return AsyncModbusSerialClient(
                self.serial_port, framer=FramerType.RTU, baudrate=self.baudrate,
                bytesize=8, parity="N", stopbits=1, **common)
        if self.transport not in (TRANSPORT_RTU_OVER_TCP, TRANSPORT_TCP):
            raise ValueError(f"unknown transport {self.transport!r}")
        framer = FramerType.RTU if self.transport == TRANSPORT_RTU_OVER_TCP else FramerType.SOCKET
        return AsyncModbusTcpClient(self.host, port=self.port, framer=framer, **common)


class FwecsaBus:
    """Serialised Modbus requests on one link, with the bus's timing rules."""

    def __init__(
        self,
        endpoint: Endpoint,
        *,
        timeout: float | None = None,
        gap: float | None = None,
        resync: float | None = None,
    ) -> None:
        self.endpoint = endpoint
        # Module constants read here, not as defaults, so tests can shorten them.
        self._timeout = REQUEST_TIMEOUT if timeout is None else timeout
        self._gap = FRAME_GAP if gap is None else gap
        self._resync = RESYNC_DELAY if resync is None else resync
        self._lock = asyncio.Lock()
        self._client: Any = None
        self._quiet_until = 0.0
        self._unit_kwarg: str | None = None
        self.requests = 0
        self.failures = 0
        self.last_error: str | None = None

    async def read(self, slave: int, table: Table, address: int, count: int) -> list[int]:
        """Read ``count`` values of one table from ``address``; bits come back as 0/1."""

        def call(client: Any) -> Awaitable[Any]:
            kwargs = {"count": count, self._unit_argument(client): slave}
            return getattr(client, READS[table])(address, **kwargs)

        what = f"read {table} {address}+{count}"
        result = await self._request(what, call)
        if result.isError():
            await self._refused(result, what, table, address, count)
        values = ([int(bool(b)) for b in result.bits[:count]] if table.bits
                  else list(result.registers))
        if len(values) != count:
            await self._fail(f"{len(values)} values for {count}")
            raise FwecsaTransientError(f"{what}: {len(values)} values")
        return values

    async def write(self, slave: int, table: Table, address: int, value: int) -> None:
        """Write one coil (FC15) or holding register (FC16). The caller reads it back.

        Same lock, quiet gap and failure handling as a read: a write is one more
        request on the one bus. A refusal (exception 1/2/3) is FwecsaIllegalError
        and leaves the link up; anything else drops it, as for a read.
        """
        if table is Table.COIL:
            if value not in (0, 1):
                raise ValueError(f"coil value {value} is not 0 or 1")
        elif table is Table.HOLDING:
            if not 0 <= value <= 0xFFFF:
                raise ValueError(f"register value {value} does not fit 16 bits")
        else:
            raise ValueError(f"{table} is read-only")

        def call(client: Any) -> Awaitable[Any]:
            kwargs = {self._unit_argument(client): slave}
            if table is Table.COIL:
                return client.write_coils(address, [bool(value)], **kwargs)
            return client.write_registers(address, [value], **kwargs)

        what = f"write {table} {address}={value}"
        result = await self._request(what, call)
        if result.isError():
            await self._refused(result, what, table, address, 1, write=value)

    async def close(self) -> None:
        async with self._lock:
            await self._drop()

    async def _request(self, what: str, call: Callable[[Any], Awaitable[Any]]) -> Any:
        async with self._lock:
            delay = self._quiet_until - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self.requests += 1
            try:
                client = await self._connected()
                result = await call(client)
            except FwecsaTransientError as err:
                await self._fail(str(err))
                raise
            except Exception as err:  # pymodbus raises a wide range on a bad link
                await self._fail(f"{type(err).__name__}: {err}")
                raise FwecsaTransientError(f"{what} on {self.endpoint}: {err}") from err
            self._quiet_until = time.monotonic() + self._gap
            return result

    async def _refused(self, result: Any, what: str, table: Table, address: int, count: int,
                       *, write: int | None = None) -> None:
        code = getattr(result, "exception_code", None)
        if code in ILLEGAL_CODES:
            raise FwecsaIllegalError(table, address, count, code, write=write)
        # 4 device failure, 6 busy, 10/11 gateway: the link, not the request.
        await self._fail(f"exception {code}")
        raise FwecsaTransientError(f"{what}: exception {code}")

    async def _connected(self) -> Any:
        if self._client is None:
            self._client = self.endpoint.make_client(self._timeout)
        if not getattr(self._client, "connected", False):
            if not await self._client.connect():
                raise FwecsaTransientError(f"cannot open {self.endpoint}")
            _LOGGER.debug("Connected to %s", self.endpoint)
        return self._client

    def _unit_argument(self, client: Any) -> str:
        """pymodbus renamed the unit argument from ``slave`` to ``device_id``."""
        if self._unit_kwarg is None:
            params = inspect.signature(client.read_holding_registers).parameters
            self._unit_kwarg = "device_id" if "device_id" in params else "slave"
        return self._unit_kwarg

    async def _fail(self, reason: str) -> None:
        self.failures += 1
        self.last_error = reason
        await self._drop()
        # Let any late reply arrive and die with the old connection, rather than
        # be read as the answer to the next request.
        self._quiet_until = time.monotonic() + self._resync

    async def _drop(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        try:
            closed = client.close()
            if inspect.isawaitable(closed):
                await closed
        except Exception:  # noqa: BLE001 - closing must never raise onward
            _LOGGER.debug("Ignoring error while closing %s", self.endpoint, exc_info=True)


class BusRegistry:
    """One bus per physical link, shared by every entry and flow that uses it."""

    def __init__(self, factory: Callable[[Endpoint], FwecsaBus] = FwecsaBus) -> None:
        self._factory = factory
        self._buses: dict[str, FwecsaBus] = {}
        self._users: dict[str, int] = {}

    def acquire(self, endpoint: Endpoint) -> FwecsaBus:
        bus = self._buses.get(endpoint.key)
        if bus is None:
            bus = self._buses[endpoint.key] = self._factory(endpoint)
        self._users[endpoint.key] = self._users.get(endpoint.key, 0) + 1
        return bus

    async def release(self, endpoint: Endpoint) -> None:
        users = self._users.get(endpoint.key, 0) - 1
        if users > 0:
            self._users[endpoint.key] = users
            return
        self._users.pop(endpoint.key, None)
        bus = self._buses.pop(endpoint.key, None)
        if bus is not None:
            await bus.close()

    def in_use(self, endpoint: Endpoint) -> bool:
        return endpoint.key in self._buses
