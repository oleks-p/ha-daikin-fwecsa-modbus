#!/usr/bin/env python3
"""A simulated FWECSA: for the tests, and for a development Home Assistant.

    python3 tools/sim_fwecsa.py --fixture tests/fixtures/fwecsa_reference.json \
        --listen 0.0.0.0:5020

serves the four tables over Modbus TCP, the way the reference bus looks to a
client: mbusd in front of the unit. That means FC1-4 read, FC15/FC16 write,
and FC5/FC6 -- which the unit does not answer -- come back as exception 11
("gateway target failed to respond"), as does any other slave address.

The unit's controller is modelled only as far as the integration can see it:
the status inputs follow the coils that command them, and the setpoint inputs
follow the holding registers. Python 3.11 and the standard library only.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import struct

TABLES = ("coil", "discrete", "holding", "input")
SIZES = {"coil": 18, "discrete": 31, "holding": 12, "input": 15}
#: Function code -> table, for reads.
READ_FC = {1: "coil", 2: "discrete", 3: "holding", 4: "input"}

ILLEGAL_FUNCTION, ILLEGAL_ADDRESS, ILLEGAL_VALUE = 1, 2, 3
GATEWAY_NO_RESPONSE = 11

#: Coils the discrete inputs mirror: unit on, winter, economy, anti-freeze.
FOLLOW_BITS = {0: 0, 1: 1, 2: 2, 3: 3}
#: Holding registers the input registers mirror: the three setpoints and humidity.
FOLLOW_WORDS = {10: 0, 11: 3, 12: 6, 13: 7}


class FakeFwecsa:
    """The four tables of one unit, and its answers.

    ``read`` and ``write`` return the values (or True) on success, an int for a
    Modbus exception, and None for no reply at all.
    """

    def __init__(self, tables: dict[str, list[int]], slave: int = 1, *,
                 auto_switching: bool = False) -> None:
        self.tables = {name: list(tables[name]) for name in TABLES}
        for name in TABLES:
            assert len(self.tables[name]) == SIZES[name], name
        self.slave = slave
        #: The unit's "Switching Summer/Winter" set to auto: input 9 follows holding 6.
        self.auto_switching = auto_switching
        self.offline = False
        #: Tables that refuse any read of more than one value.
        self.refuse_blocks: set[str] = set()
        #: (table, address) a write is acknowledged for but not applied.
        self.ignore: set[tuple[str, int]] = set()
        self.requests: list[tuple[int, str, int, int]] = []
        self.writes: list[tuple[int, str, int, int]] = []

    @classmethod
    def from_fixture(cls, path: str | pathlib.Path, **kwargs) -> FakeFwecsa:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        return cls(data["tables"], data.get("slave", 1), **kwargs)

    def read(self, slave: int, fc: int, address: int, count: int) -> list[int] | int | None:
        if self.offline:
            return None
        if slave != self.slave:
            return GATEWAY_NO_RESPONSE
        table = READ_FC.get(fc)
        if table is None:
            return ILLEGAL_FUNCTION
        self.requests.append((fc, table, address, count))
        if count < 1 or address < 0 or address + count > SIZES[table]:
            return ILLEGAL_ADDRESS
        if count > 1 and table in self.refuse_blocks:
            return ILLEGAL_ADDRESS
        return self.tables[table][address:address + count]

    def write(self, slave: int, fc: int, address: int, values: list[int]) -> bool | int | None:
        if self.offline:
            return None
        if slave != self.slave:
            return GATEWAY_NO_RESPONSE
        if fc in (5, 6):
            # Not answered by the unit; mbusd gives up and says so.
            return GATEWAY_NO_RESPONSE
        table = {15: "coil", 16: "holding"}.get(fc)
        if table is None:
            return ILLEGAL_FUNCTION
        if not values or address < 0 or address + len(values) > SIZES[table]:
            return ILLEGAL_ADDRESS
        for offset, raw in enumerate(values):
            self.writes.append((fc, table, address + offset, raw))
            if (table, address + offset) not in self.ignore:
                self.tables[table][address + offset] = int(bool(raw)) if table == "coil" else raw
        self.follow()
        return True

    def follow(self) -> None:
        """The controller's side: status follows command."""
        coils, holding = self.tables["coil"], self.tables["holding"]
        for di, coil in FOLLOW_BITS.items():
            self.tables["discrete"][di] = coils[coil]
        for ir, hr in FOLLOW_WORDS.items():
            self.tables["input"][ir] = holding[hr]
        if self.auto_switching:
            active = holding[6]
        else:
            active = holding[3] if self.tables["discrete"][1] else holding[0]
        self.tables["input"][9] = active


# -- Modbus TCP --------------------------------------------------------------------


def _pack_bits(bits: list[int]) -> bytes:
    out = bytearray((len(bits) + 7) // 8)
    for i, bit in enumerate(bits):
        if bit:
            out[i // 8] |= 1 << (i % 8)
    return bytes(out)


def _unpack_bits(data: bytes, count: int) -> list[int]:
    return [(data[i // 8] >> (i % 8)) & 1 for i in range(count)]


def handle_pdu(fake: FakeFwecsa, unit: int, pdu: bytes) -> bytes:
    """One request PDU -> its response PDU."""
    fc = pdu[0]

    def error(code: int) -> bytes:
        return bytes([fc | 0x80, code])

    if fc in READ_FC:
        address, count = struct.unpack(">HH", pdu[1:5])
        result = fake.read(unit, fc, address, count)
        if result is None:
            return error(GATEWAY_NO_RESPONSE)
        if isinstance(result, int):
            return error(result)
        if fc in (1, 2):
            payload = _pack_bits(result)
        else:
            payload = b"".join(struct.pack(">H", v) for v in result)
        return bytes([fc, len(payload)]) + payload
    if fc in (5, 6):
        address, raw = struct.unpack(">HH", pdu[1:5])
        result = fake.write(unit, fc, address, [raw])
    elif fc in (15, 16):
        address, count, _length = struct.unpack(">HHB", pdu[1:6])
        data = pdu[6:]
        values = (_unpack_bits(data, count) if fc == 15
                  else list(struct.unpack(f">{count}H", data[:2 * count])))
        result = fake.write(unit, fc, address, values)
        if result is True:
            return pdu[:5]
    else:
        return error(ILLEGAL_FUNCTION)
    if result is None or result is True:
        return error(GATEWAY_NO_RESPONSE)
    return error(result)


class TcpServer:
    """Modbus TCP (MBAP) in front of one FakeFwecsa."""

    def __init__(self, fake: FakeFwecsa, host: str = "127.0.0.1", port: int = 0) -> None:
        self.fake, self.host, self.port = fake, host, port
        self._server: asyncio.base_events.Server | None = None

    async def start(self) -> int:
        self._server = await asyncio.start_server(self._client, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]
        return self.port

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                header = await reader.readexactly(7)
                tid, pid, length, unit = struct.unpack(">HHHB", header)
                pdu = await reader.readexactly(length - 1)
                if self.fake.offline:
                    continue  # nothing answers: let the client time out
                reply = handle_pdu(self.fake, unit, pdu)
                writer.write(struct.pack(">HHHB", tid, pid, len(reply) + 1, unit) + reply)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()


async def _serve(args: argparse.Namespace) -> None:
    fake = FakeFwecsa.from_fixture(args.fixture, auto_switching=args.auto_switching)
    host, _, port = args.listen.rpartition(":")
    server = TcpServer(fake, host or "0.0.0.0", int(port))
    await server.start()
    print(f"FWECSA simulator: slave {fake.slave} on {server.host}:{server.port} (Modbus TCP)",
          flush=True)
    await asyncio.Event().wait()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--fixture", required=True, help="tables to serve (JSON)")
    parser.add_argument("--listen", default="127.0.0.1:5020", help="host:port")
    parser.add_argument("--auto-switching", action="store_true",
                        help="summer/winter switching on water/air temperature")
    asyncio.run(_serve(parser.parse_args()))


if __name__ == "__main__":
    main()
