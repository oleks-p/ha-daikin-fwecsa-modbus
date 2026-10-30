"""The register map against the manual's tables, and the platforms against the map."""

from __future__ import annotations

from custom_components.daikin_fwecsa_modbus.binary_sensor import BINARY_SENSORS
from custom_components.daikin_fwecsa_modbus.block_planner import plan_blocks
from custom_components.daikin_fwecsa_modbus.coordinator import decode
from custom_components.daikin_fwecsa_modbus.number import NUMBERS
from custom_components.daikin_fwecsa_modbus.registers import (
    BY_KEY,
    CONSENT,
    REGISTERS,
    TABLE_SIZES,
    WRITE_SPECS,
    Table,
)
from custom_components.daikin_fwecsa_modbus.select import SELECTS
from custom_components.daikin_fwecsa_modbus.sensor import SENSORS
from custom_components.daikin_fwecsa_modbus.switch import SWITCHES


def test_every_documented_variable_is_mapped_once():
    for table, size in TABLE_SIZES.items():
        addresses = [r.address for r in REGISTERS if r.table is table]
        assert addresses == list(range(size)), table
    assert len(BY_KEY) == len(REGISTERS) == 18 + 31 + 12 + 15


def test_addresses_are_the_manual_number_minus_one():
    # The ones the reference unit's YAML and i3 bridges established.
    assert BY_KEY["power"].number == 1
    assert BY_KEY["room_temperature"].number == 1
    assert BY_KEY["water_temperature"].address == 2
    assert BY_KEY["single_setpoint"].number == 7
    assert BY_KEY["fan_speed"].number == 11
    assert BY_KEY["valve_open"].number == 26


def test_every_register_has_an_entity():
    """'Entities for all available registers': read-only ones at least."""
    read_only = {d.key for d in SENSORS} | {d.key for d in BINARY_SENSORS}
    assert {r.key for r in REGISTERS} <= read_only


def test_every_writable_register_has_a_writable_entity():
    writable = {r.key for r in REGISTERS if r.table.writable}
    assert set(WRITE_SPECS) == writable
    # Each on the platform its WriteSpec names: the mode and the fan speed are selects.
    for platform, descriptions in (("switch", SWITCHES), ("number", NUMBERS),
                                   ("select", SELECTS)):
        assert {d.key for d in descriptions} == {
            key for key, spec in WRITE_SPECS.items() if spec.platform == platform}


def test_consent_names_a_master_coil():
    for key, consent in CONSENT.items():
        assert key in WRITE_SPECS
        assert BY_KEY[consent].table is Table.COIL and consent.startswith("master_")


def test_one_read_per_table():
    blocks = plan_blocks(REGISTERS)
    assert [(b.table, b.address, b.count) for b in blocks] == [
        (Table.COIL, 0, 18), (Table.DISCRETE, 0, 31), (Table.HOLDING, 0, 12),
        (Table.INPUT, 0, 15)]


def test_decode():
    room = BY_KEY["room_temperature"]
    assert decode(room, 230) == 23.0
    assert decode(room, (-52) & 0xFFFF) == -5.2
    assert decode(room, 0x8000) is None            # far outside the probes' range
    assert decode(BY_KEY["valve_open"], 1) is True
    assert decode(BY_KEY["fan_speed"], 4) == 4
