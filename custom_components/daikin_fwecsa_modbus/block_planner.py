"""Turn the register map into the fewest reads: one per table.

Every table is a single run from address 0 (the manual lists no gaps), so each
is read whole in one request -- four requests a poll. If the unit refuses a
block, the coordinator falls back to reading that table one value at a time,
for good: a fixed fallback, never a search for the largest count that works.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .registers import MAX_READ, Reg, Table


@dataclass(frozen=True, slots=True)
class Block:
    """One read request: ``count`` values of ``table`` from ``address``."""

    table: Table
    address: int
    count: int
    registers: tuple[Reg, ...]

    @property
    def end(self) -> int:
        return self.address + self.count - 1

    @property
    def key(self) -> str:
        return f"{self.table}:{self.address}+{self.count}"

    def __str__(self) -> str:
        return f"{self.table} {self.address}..{self.end}"


def plan_blocks(registers: Iterable[Reg]) -> tuple[Block, ...]:
    """Group registers into per-table reads, each as long as the protocol allows."""
    by_table: dict[Table, list[Reg]] = {}
    for reg in sorted(registers, key=lambda r: (list(Table).index(r.table), r.address)):
        by_table.setdefault(reg.table, []).append(reg)
    blocks: list[Block] = []
    for table, regs in by_table.items():
        current: list[Reg] = []
        for reg in regs:
            if current and reg.address - current[0].address + 1 > MAX_READ[table]:
                blocks.append(_block(table, current))
                current = []
            current.append(reg)
        if current:
            blocks.append(_block(table, current))
    return tuple(blocks)


def split(block: Block) -> tuple[Block, ...]:
    """One read per value: the fallback when the unit rejects a block."""
    return tuple(Block(block.table, r.address, 1, (r,)) for r in block.registers)


def _block(table: Table, regs: list[Reg]) -> Block:
    start = regs[0].address
    return Block(table, start, regs[-1].address - start + 1, tuple(regs))


def describe(blocks: Iterable[Block]) -> list[str]:
    """One line per read, for diagnostics."""
    return [f"{b}: {b.count} value(s)" for b in blocks]
