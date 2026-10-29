"""Home Assistant fixtures: the integration against a simulated FWECSA.

The fake answers like the reference bus does -- the unit behind mbusd: FC1-4
and FC15/FC16 only, and "gateway target failed to respond" for anything else
-- so the transport, the decoders and the entity set run against what the
hardware does, not against what the code assumes.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util
from pymodbus.exceptions import ConnectionException, ModbusIOException
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.daikin_fwecsa_modbus.const import (
    CONF_ALLOW_WRITES,
    CONF_ENTITY_PREFIX,
    CONF_SLAVE,
    CONF_SWITCHING,
    CONF_TRANSPORT,
    DOMAIN,
    TRANSPORT_TCP,
)
from tests.sim import FakeFwecsa

FIXTURE = Path(__file__).parents[1] / "fixtures" / "fwecsa_reference.json"
TRANSPORT = "custom_components.daikin_fwecsa_modbus.transport"

TCP_DATA = {
    CONF_TRANSPORT: TRANSPORT_TCP,
    "host": "127.0.0.1",
    "port": 10502,
    CONF_SLAVE: 1,
    CONF_ENTITY_PREFIX: "fancoil",
}


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


class FakeResponse:
    def __init__(self, values: list[int] | None = None, code: int | None = None,
                 *, bits: bool = False) -> None:
        values = values or []
        # pymodbus pads bits to a whole byte.
        self.bits = [bool(v) for v in values] + [False] * (-len(values) % 8) if bits else []
        self.registers = [] if bits else values
        self.exception_code = code

    def isError(self) -> bool:  # noqa: N802 - pymodbus spelling
        return self.exception_code is not None


class FakeModbusClient:
    """The slice of pymodbus the transport uses, answering from a FakeFwecsa."""

    def __init__(self, fake: FakeFwecsa, *args, **kwargs) -> None:
        self.fake = fake
        self.args, self.kwargs = args, kwargs
        self.connected = False
        self.closes = 0

    async def connect(self) -> bool:
        if self.fake.offline:
            return False
        self.connected = True
        return True

    def close(self) -> None:
        self.connected = False
        self.closes += 1

    def _read(self, fc: int, address: int, count: int, device_id: int) -> FakeResponse:
        if not self.connected:
            raise ConnectionException("not connected")
        result = self.fake.read(device_id, fc, address, count)
        if result is None:
            raise ModbusIOException("no response")
        if isinstance(result, int):
            return FakeResponse(code=result)
        return FakeResponse(result, bits=fc in (1, 2))

    async def read_coils(self, address, *, count=1, device_id=1, no_response_expected=False):
        return self._read(1, address, count, device_id)

    async def read_discrete_inputs(self, address, *, count=1, device_id=1,
                                   no_response_expected=False):
        return self._read(2, address, count, device_id)

    async def read_holding_registers(self, address, *, count=1, device_id=1,
                                     no_response_expected=False):
        return self._read(3, address, count, device_id)

    async def read_input_registers(self, address, *, count=1, device_id=1,
                                   no_response_expected=False):
        return self._read(4, address, count, device_id)

    def _write(self, fc: int, address: int, values: list[int], device_id: int) -> FakeResponse:
        if not self.connected:
            raise ConnectionException("not connected")
        outcome = self.fake.write(device_id, fc, address, values)
        if outcome is None:
            raise ModbusIOException("no response")
        return FakeResponse() if outcome is True else FakeResponse(code=outcome)

    async def write_coils(self, address, values, *, device_id=1, no_response_expected=False):
        return self._write(15, address, [int(bool(v)) for v in values], device_id)

    async def write_registers(self, address, values, *, device_id=1,
                              no_response_expected=False):
        return self._write(16, address, list(values), device_id)

    async def write_coil(self, address, value, *, device_id=1, no_response_expected=False):
        return self._write(5, address, [int(bool(value))], device_id)

    async def write_register(self, address, value, *, device_id=1, no_response_expected=False):
        return self._write(6, address, [value], device_id)


@pytest.fixture
def fake() -> FakeFwecsa:
    fake = FakeFwecsa.from_fixture(FIXTURE)
    yield fake
    # The unit does not answer FC5/FC6: no test may make the integration use them.
    assert not [w for w in fake.writes if w[0] in (5, 6)], fake.writes


@pytest.fixture
def modbus_clients(fake):
    """Every pymodbus client the integration creates, in order."""
    clients: list[FakeModbusClient] = []

    def factory(*args, **kwargs):
        client = FakeModbusClient(fake, *args, **kwargs)
        clients.append(client)
        return client

    with (
        patch(f"{TRANSPORT}.AsyncModbusSerialClient", side_effect=factory),
        patch(f"{TRANSPORT}.AsyncModbusTcpClient", side_effect=factory),
        patch(f"{TRANSPORT}.FRAME_GAP", 0),
        patch(f"{TRANSPORT}.RESYNC_DELAY", 0),
    ):
        yield clients


@pytest.fixture
def config_entry(hass) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="FWECSA 1",
        unique_id="tcp:127.0.0.1:10502#1",
        data=dict(TCP_DATA),
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def writes_on(hass, config_entry):
    """Allow writes, with the factory switching (keyboard/serial)."""
    hass.config_entries.async_update_entry(config_entry, options={CONF_ALLOW_WRITES: True})
    return config_entry


@pytest.fixture
def auto_switching(hass, config_entry, fake):
    """Allow writes, the unit switching summer/winter on water temperature."""
    fake.auto_switching = True
    hass.config_entries.async_update_entry(
        config_entry, options={CONF_ALLOW_WRITES: True, CONF_SWITCHING: "auto_water"})
    return config_entry


@pytest.fixture
async def setup_integration(hass, config_entry, modbus_clients, freezer):
    # The clock is frozen before the first poll, so the coordinator's outage
    # timing (time.monotonic) and the tests' time travel share one clock.
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


@pytest.fixture
def advance(hass, freezer):
    """Move time forward in 10 s steps, letting each poll complete."""

    async def run(seconds: float) -> None:
        remaining = seconds
        while remaining > 0:
            step = min(10, remaining)
            freezer.tick(timedelta(seconds=step))
            async_fire_time_changed(hass, dt_util.utcnow())
            await hass.async_block_till_done()
            remaining -= step

    return run
