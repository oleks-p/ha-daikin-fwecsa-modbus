"""The bus: function codes, failure kinds, and a real pymodbus client end to end."""

from __future__ import annotations

import pytest
from pymodbus.client import AsyncModbusTcpClient

from custom_components.daikin_fwecsa_modbus.registers import Table
from custom_components.daikin_fwecsa_modbus.transport import (
    Endpoint,
    FwecsaBus,
    FwecsaIllegalError,
    FwecsaTransientError,
)
from tests.sim import FakeFwecsa, TcpServer

from .conftest import FIXTURE, TCP_DATA


def _bus(**kwargs) -> FwecsaBus:
    return FwecsaBus(Endpoint.from_config(TCP_DATA), gap=0, resync=0, **kwargs)


async def test_reads_each_table_with_its_function_code(fake, modbus_clients):
    bus = _bus()
    assert await bus.read(1, Table.COIL, 0, 2) == [1, 1]
    assert await bus.read(1, Table.DISCRETE, 0, 31) == fake.tables["discrete"]
    assert await bus.read(1, Table.HOLDING, 6, 1) == [230]
    assert await bus.read(1, Table.INPUT, 0, 3) == [230, 0, 290]
    assert [fc for fc, *_ in fake.requests] == [1, 2, 3, 4]


async def test_writes_use_fc15_and_fc16_only(fake, modbus_clients):
    bus = _bus()
    await bus.write(1, Table.COIL, 2, 1)
    await bus.write(1, Table.HOLDING, 0, 255)
    assert fake.writes == [(15, "coil", 2, 1), (16, "holding", 0, 255)]
    with pytest.raises(ValueError):
        await bus.write(1, Table.INPUT, 0, 1)
    with pytest.raises(ValueError):
        await bus.write(1, Table.COIL, 0, 2)


async def test_a_refusal_is_illegal_and_keeps_the_link(fake, modbus_clients):
    bus = _bus()
    with pytest.raises(FwecsaIllegalError) as err:
        await bus.read(1, Table.HOLDING, 0, 13)    # one past the table
    assert err.value.code == 2
    assert bus.failures == 0 and modbus_clients[0].closes == 0


async def test_no_answer_is_transient_and_drops_the_link(fake, modbus_clients):
    bus = _bus()
    with pytest.raises(FwecsaTransientError):
        await bus.read(7, Table.INPUT, 0, 1)        # gateway: target failed to respond
    assert bus.failures == 1 and modbus_clients[0].closes == 1
    fake.offline = True
    with pytest.raises(FwecsaTransientError):
        await bus.read(1, Table.INPUT, 0, 1)


async def test_end_to_end_through_a_modbus_tcp_server(socket_enabled):
    """The real pymodbus client, through the simulator's MBAP server."""
    fake = FakeFwecsa.from_fixture(FIXTURE)
    server = TcpServer(fake)
    port = await server.start()
    bus = FwecsaBus(Endpoint.from_config({**TCP_DATA, "port": port}), gap=0, resync=0,
                    timeout=2)
    try:
        assert await bus.read(1, Table.COIL, 0, 18) == fake.tables["coil"]
        assert await bus.read(1, Table.DISCRETE, 0, 31) == fake.tables["discrete"]
        assert await bus.read(1, Table.INPUT, 0, 15) == fake.tables["input"]
        await bus.write(1, Table.COIL, 2, 1)
        await bus.write(1, Table.HOLDING, 3, 215)
        assert await bus.read(1, Table.COIL, 2, 1) == [1]
        assert await bus.read(1, Table.HOLDING, 3, 1) == [215]
        assert fake.tables["discrete"][2] == 1      # economy on follows its coil

        # What the unit does with a single write: nothing; the gateway says so.
        client = AsyncModbusTcpClient("127.0.0.1", port=port, timeout=2, retries=0)
        await client.connect()
        result = await client.write_register(3, 220, device_id=1)
        assert result.isError() and result.exception_code == 11
        client.close()
        assert fake.tables["holding"][3] == 215
    finally:
        await bus.close()
        await server.stop()
