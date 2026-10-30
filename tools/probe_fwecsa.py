#!/usr/bin/env python3
"""Read every documented FWECSA variable once, and write a capture.

    python3 tools/probe_fwecsa.py --tcp 127.0.0.1:10502 --slave 1 -o capture.json
    python3 tools/probe_fwecsa.py --serial /dev/ttyUSB0 --baud 9600 --slave 1

READ-ONLY: function codes 1-4 and nothing else. Run it with the integration
loaded or not: through a gateway such as mbusd the requests queue with
everyone else's. On a bare serial port, stop whatever else owns the port first.

For each table it records:

* the whole table in one read, as the integration reads it;
* each value on its own, to see whether the two agree;
* one address past the documented end, to see where the unit's table stops.

The capture's ``tables`` section has the same shape as
tests/fixtures/fwecsa_reference.json, so the simulator serves a capture as it
stands: tests/fixtures/fwecsa_capture.json is the reference unit's.

Python 3.11 and pymodbus 3.6 or later.
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import sys
import time
from datetime import UTC, datetime

from pymodbus import FramerType
from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient

SIZES = {"coil": 18, "discrete": 31, "holding": 12, "input": 15}
READS = {"coil": "read_coils", "discrete": "read_discrete_inputs",
         "holding": "read_holding_registers", "input": "read_input_registers"}


def _client(args: argparse.Namespace):
    common = {"timeout": args.timeout, "retries": 0}
    if args.serial:
        return AsyncModbusSerialClient(args.serial, framer=FramerType.RTU, baudrate=args.baud,
                                       bytesize=8, parity="N", stopbits=1, **common)
    host, _, port = (args.tcp or args.rtu_over_tcp).rpartition(":")
    framer = FramerType.RTU if args.rtu_over_tcp else FramerType.SOCKET
    return AsyncModbusTcpClient(host, port=int(port), framer=framer, **common)


async def _read(client, unit_kwarg: str, slave: int, table: str, address: int, count: int,
                gap: float) -> dict:
    started = time.monotonic()
    try:
        result = await getattr(client, READS[table])(address, count=count,
                                                     **{unit_kwarg: slave})
    except Exception as err:  # noqa: BLE001 - a probe records every failure
        outcome: dict = {"error": f"{type(err).__name__}: {err}"}
    else:
        if result.isError():
            outcome = {"exception": getattr(result, "exception_code", None)}
        elif table in ("coil", "discrete"):
            outcome = {"values": [int(bool(b)) for b in result.bits[:count]]}
        else:
            outcome = {"values": list(result.registers)}
    outcome["ms"] = round((time.monotonic() - started) * 1000)
    await asyncio.sleep(gap)
    return outcome


async def probe(args: argparse.Namespace) -> dict:
    client = _client(args)
    if not await client.connect():
        raise SystemExit(f"cannot connect: {args.serial or args.tcp or args.rtu_over_tcp}")
    params = inspect.signature(client.read_holding_registers).parameters
    unit_kwarg = "device_id" if "device_id" in params else "slave"
    capture: dict = {
        "source": f"tools/probe_fwecsa.py, {datetime.now(UTC).isoformat(timespec='seconds')}",
        "slave": args.slave,
        "link": args.serial or args.tcp or args.rtu_over_tcp,
        "tables": {},
        "block": {},
        "single": {},
        "past_end": {},
    }
    try:
        for table, size in SIZES.items():
            block = await _read(client, unit_kwarg, args.slave, table, 0, size, args.gap)
            capture["block"][table] = block
            singles = [await _read(client, unit_kwarg, args.slave, table, a, 1, args.gap)
                       for a in range(size)]
            capture["single"][table] = singles
            capture["past_end"][table] = await _read(client, unit_kwarg, args.slave, table,
                                                     size, 1, args.gap)
            if "values" in block:
                capture["tables"][table] = block["values"]
            elif all("values" in s for s in singles):
                capture["tables"][table] = [s["values"][0] for s in singles]
            print(f"{table:9} block: {block}", file=sys.stderr)
    finally:
        result = client.close()
        if inspect.isawaitable(result):
            await result
    return capture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    link = parser.add_mutually_exclusive_group(required=True)
    link.add_argument("--tcp", metavar="HOST:PORT", help="Modbus TCP gateway (e.g. mbusd)")
    link.add_argument("--rtu-over-tcp", metavar="HOST:PORT", help="transparent serial server")
    link.add_argument("--serial", metavar="PORT", help="local RS-485 adapter")
    parser.add_argument("--baud", type=int, default=9600)
    parser.add_argument("--slave", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=3.0,
                        help="per request; keep it above the gateway's own retries")
    parser.add_argument("--gap", type=float, default=0.05, help="pause between requests (s)")
    parser.add_argument("-o", "--output", help="write the capture here (default: stdout)")
    args = parser.parse_args()
    capture = asyncio.run(probe(args))
    text = json.dumps(capture, indent=1) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as out:
            out.write(text)
    else:
        sys.stdout.write(text)


if __name__ == "__main__":
    main()
