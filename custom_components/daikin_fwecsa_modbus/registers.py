"""The FWECSA register map: every variable the manual lists, in its four tables.

Protocol only. What an entity shows -- unit, device class, name -- lives with
the entity descriptions in the platform modules.

Source: Daikin "FWECSA Installation and operation manual", FC66003946 Rev 00,
section NETWORKS AND CONNECTIVITY (English p. 16-17). The manual numbers each
table's variables from 1; Modbus addresses them from 0, so every address here
is the manual's number minus one (``Reg.number`` gives the number back).

What the manual does not say, and where it came from instead:

* **Scale.** Temperatures are tenths of a degree. Measured on the reference
  unit (an FWB15CTV) on 2026-10-29: input 0 read 230 with the room at 23.0 C,
  input 2 read 290 with the water at 29.0 C, holding 6 read 230 with the
  setpoint at 23.0. Signed: probed on 2026-10-30, holding 0 read 0xDC00 and
  input 10 reported 100, the minimum in holding 1, as the unit does with
  -921.6 C. Humidity setpoints are whole percent (their limits read 35 and
  75); room humidity and the other percentages are taken to be: unverified,
  the reference unit has no humidity probe and its outputs were idle.
* **Summer/winter.** Coil 1 and discrete input 1 read 1 in winter (heating):
  the reference unit read 1 while heating, and so does the i3 controller's
  bridge of the same unit. With switching on water temperature the coil is
  not what decides: probed, coil 1 read 0 and input 1 read 1, heating.
* **Two-way flags** (discrete inputs 9-12 and 27). The manual gives the two
  meanings in brackets, "Speed number (3/4)"; 1 is taken to be the second.
  The reference unit agrees for inputs 10 (0 with no hot-water probe: 2
  pipes) and 27 (1 with the speed set to auto). Inputs 9, 11 and 12 are
  unverified.
* **Function codes.** The unit answers FC1-4 and writes only with FC15 and
  FC16, as the manual lists; FC5 and FC6 get no reply (measured).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

REGISTER_MAP_VERSION = "fwecsa-fc66003946-rev00"


class Table(StrEnum):
    """A Modbus data table, named for what the manual calls it."""

    COIL = "coil"            # COIL STATUS: read FC1, write FC15
    DISCRETE = "discrete"    # INPUT STATUS: read FC2
    HOLDING = "holding"      # HOLDING REGISTER: read FC3, write FC16
    INPUT = "input"          # INPUT REGISTER: read FC4

    @property
    def bits(self) -> bool:
        return self in (Table.COIL, Table.DISCRETE)

    @property
    def writable(self) -> bool:
        return self in (Table.COIL, Table.HOLDING)


#: How many variables the manual lists per table.
TABLE_SIZES: dict[Table, int] = {
    Table.COIL: 18, Table.DISCRETE: 31, Table.HOLDING: 12, Table.INPUT: 15,
}
#: Modbus allows 2000 bits or 125 registers per read; nothing here comes close.
MAX_READ = {Table.COIL: 2000, Table.DISCRETE: 2000, Table.HOLDING: 125, Table.INPUT: 125}

#: The NTC probes cover -25..100 C (TECHNICAL DATA). Outside a wider band than
#: that, a reading is noise or an open/shorted probe and decodes to None.
TEMPERATURE_SANE = (-40.0, 120.0)


@dataclass(frozen=True, slots=True)
class Reg:
    """One variable: a bit (coils, discrete inputs) or a 16-bit word."""

    key: str
    table: Table
    address: int
    #: The manual's own description, verbatim (docs/register_map.md lists it).
    manual: str = ""
    scale: float = 1.0
    signed: bool = False
    #: Values outside this band are noise, not readings, and decode to None.
    sane: tuple[float, float] | None = None

    @property
    def number(self) -> int:
        """The manual's number for this variable."""
        return self.address + 1

    @property
    def ref(self) -> str:
        return f"{self.table}:{self.address}"


_T = {"scale": 0.1, "signed": True, "sane": TEMPERATURE_SANE}


def _table(table: Table, rows: list[tuple]) -> list[Reg]:
    """(key, manual text[, Reg options]) per variable, in the manual's order."""
    return [Reg(row[0], table, address, row[1], **(row[2] if len(row) > 2 else {}))
            for address, row in enumerate(rows)]


#: COIL STATUS (digital, read/write). The "from MASTER" coils are the consent
#: for each function: with one off, the unit may keep obeying its own keyboard
#: for that function whatever Modbus writes.
COILS = _table(Table.COIL, [
    ("power", "ON/OFF controller"),
    ("mode", "SUMMER/WINTER controller"),                 # 1 = winter: heating
    ("economy", "ECONOMY controller"),
    ("anti_freeze", "ENABLE ANTI-FREEZE controller"),     # minimum room temperature
    ("electric_heater", "ENABLE ELECTRICAL HEATER controller"),
    ("modulating_fan_auto", "modulating ventilation MAN/AUTO controller"),
    ("master_power", "enable ON/OFF from MASTER"),
    ("master_economy", "enable ECONOMY from MASTER"),
    ("master_mode", "enable SUMMER/WINTER from MASTER"),
    ("master_anti_freeze", "enable ANTI-FREEZE from MASTER"),
    ("master_electric_heater", "enable ELECTRIC HEATERS from MASTER"),
    ("master_setpoint", "enable SETPOINT from MASTER"),
    ("master_setpoint_limits", "enable SETPOINT LIMITS from MASTER"),
    ("master_fan_speed", "enable VENTILATION SPEED from MASTER"),
    ("keyboard_lock", "KEYBOARD LOCK controller"),
    ("master_humidity", "enable HUMIDITY CONTROL consent from MASTER"),
    ("humidity_control", "enable HUMIDITY CONTROL"),
    ("output_7_command", "control for CONFIGURABLE DIGITAL OUTPUT NO.7"),
])

#: INPUT STATUS (digital, read-only).
DISCRETE_INPUTS = _table(Table.DISCRETE, [
    ("unit_on", "unit ON/OFF"),
    ("mode_in_use", "SUMMER/WINTER"),                     # 1 = winter: heating
    ("economy_on", "ECONOMY on"),
    ("anti_freeze_on", "ANTI-FREEZE on"),
    ("alarm", "ALARM installed"),                         # Italian: "presenza di ALLARME"
    ("room_probe_alarm", "Room temperature probe alarm"),
    ("water_probe_alarm", "Water temperature probe alarm"),
    ("hot_water_probe_alarm", "Hot water temperature probe alarm (only with 4-pipe units)"),
    ("humidity_probe_alarm", "Room humidity probe alarm"),
    ("four_speeds", "Speed number (3/4)"),
    ("four_pipes", "Pipe number (2/4)"),
    ("modulating_fan", "Type of ventilation (STEP/MODULATING)"),
    ("board_probe", "Adjustment probe (DISPLAY/BOARD)"),
    ("heaters_installed", "Installed electrical heaters"),
    ("humidity_probe_installed", "Installed humidity probe"),
    *((f"output_{n}", f"Digital output {n} status (O{n})") for n in range(1, 8)),
    ("water_probe_present", "Water probe presence"),
    ("hot_water_probe_present", "Hot water probe presence (hydronic unit with 4 pipes)"),
    ("dehumidifying", "Dehumidification active"),
    ("valve_open", "Valve open"),
    ("off_by_contact", "Hydronic unit switched off from remote contact"),
    ("fan_auto_mode", "Ventilation control (manual/automatic)"),
    ("heater_on", "Heater active"),
    ("valve_present", "Valve presence"),
    ("economy_by_contact", "Enable ECONOMY from contact"),
])

#: HOLDING REGISTER (read/write).
HOLDING_REGISTERS = _table(Table.HOLDING, [
    ("cooling_setpoint", "Summer temperature SET (cooling)", _T),
    ("cooling_setpoint_min", "Summer temperature SET minimum limit", _T),
    ("cooling_setpoint_max", "Summer temperature SET maximum limit", _T),
    ("heating_setpoint", "Winter temperature SET (heating)", _T),
    ("heating_setpoint_min", "Winter temperature SET minimum limit", _T),
    ("heating_setpoint_max", "Winter temperature SET maximum limit", _T),
    # Live only with Summer/Winter switching on water or air temperature.
    ("single_setpoint", "Single temperature SET (if SUM/WIN on water/air temp.)", _T),
    ("humidity_setpoint", "Humidity SET"),
    ("humidity_setpoint_min", "Minimum humidity SET limit"),
    ("humidity_setpoint_max", "Maximum humidity SET limit"),
    ("fan_speed", "Step ventilation speeds"),
    ("modulating_fan_speed", "Modulating ventilation speed"),
])

#: INPUT REGISTER (read-only).
INPUT_REGISTERS = _table(Table.INPUT, [
    ("room_temperature", "Room temperature", _T),
    ("room_humidity", "Room humidity"),
    ("water_temperature", "Water temperature", _T),
    ("hot_water_temperature", "Hot water temperature (only with 4-pipe units)", _T),
    ("fan_status", "Step ventilation status"),
    ("modulating_fan_output", "Modulating ventilation % value"),
    ("analog_output_1", "% value of analogue output 1"),
    ("analog_output_2", "% value of analogue output 2"),
    ("analog_output_3", "% value of analogue output 3"),
    ("active_setpoint", "Temperature SET on", _T),
    ("cooling_setpoint_status", "Summer temperature SET", _T),
    ("heating_setpoint_status", "Winter temperature SET", _T),
    ("single_setpoint_status", "Single temperature SET (if SUM/WIN on water/air temp.)", _T),
    ("active_humidity_setpoint", "Humidity SET on"),
    ("valve_type", "Type of valve (NOT INCLUDED/ON-OFF/MODULATING)"),
])

REGISTERS: tuple[Reg, ...] = (*COILS, *DISCRETE_INPUTS, *HOLDING_REGISTERS, *INPUT_REGISTERS)
BY_KEY: dict[str, Reg] = {reg.key: reg for reg in REGISTERS}

# -- enumerations ----------------------------------------------------------------

#: Holding 11: the commanded speed. Extra-low exists on 4-speed units only.
FAN_SPEEDS: dict[int, str] = {0: "extra_low", 1: "low", 2: "medium", 3: "high", 4: "auto"}
#: Input 5: what the fan is doing. Note the offset against FAN_SPEEDS: 0 is off.
FAN_STATUSES: dict[int, str] = {0: "off", 1: "extra_low", 2: "low", 3: "medium", 4: "high"}
#: Input 15, in the manual's order (NOT INCLUDED/ON-OFF/MODULATING).
VALVE_TYPES: dict[int, str] = {0: "none", 1: "on_off", 2: "modulating"}
#: Coil 1 and discrete input 1, the manual's SUMMER/WINTER, in the words the
#: climate entity uses. Heating first, the order the select offers them in.
MODES: dict[int, str] = {1: "heating", 0: "cooling"}

ENUMS: dict[str, dict[int, str]] = {
    "mode": MODES,
    "mode_in_use": MODES,
    "fan_speed": FAN_SPEEDS,
    "fan_status": FAN_STATUSES,
    "valve_type": VALVE_TYPES,
}

# -- writes --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WriteSpec:
    """What may be written to one coil or holding register."""

    key: str
    platform: str          # "switch", "number" or "select"
    minimum: float = 0
    maximum: float = 1
    step: float = 1


def _setpoint(key: str) -> WriteSpec:
    # The unit enforces its own limits (holding 2-3 and 5-6) on top of these.
    return WriteSpec(key, "number", 5.0, 40.0, 0.1)


WRITE_SPECS: dict[str, WriteSpec] = {
    **{reg.key: WriteSpec(reg.key, "switch") for reg in COILS if reg.key not in ENUMS},
    "mode": WriteSpec("mode", "select"),
    **{key: _setpoint(key) for key in (
        "cooling_setpoint", "cooling_setpoint_min", "cooling_setpoint_max",
        "heating_setpoint", "heating_setpoint_min", "heating_setpoint_max",
        "single_setpoint")},
    **{key: WriteSpec(key, "number", 0, 100, 1) for key in (
        "humidity_setpoint", "humidity_setpoint_min", "humidity_setpoint_max",
        "modulating_fan_speed")},
    "fan_speed": WriteSpec("fan_speed", "select", 0, max(FAN_SPEEDS), 1),
}

#: The consent coil each writable function depends on. A write the unit does
#: not apply names it in the error, since a consent left off looks exactly like
#: a dead register map: the write is acknowledged and nothing changes.
CONSENT: dict[str, str] = {
    "power": "master_power",
    "mode": "master_mode",
    "economy": "master_economy",
    "anti_freeze": "master_anti_freeze",
    "electric_heater": "master_electric_heater",
    "cooling_setpoint": "master_setpoint",
    "heating_setpoint": "master_setpoint",
    "single_setpoint": "master_setpoint",
    "cooling_setpoint_min": "master_setpoint_limits",
    "cooling_setpoint_max": "master_setpoint_limits",
    "heating_setpoint_min": "master_setpoint_limits",
    "heating_setpoint_max": "master_setpoint_limits",
    "fan_speed": "master_fan_speed",
    "modulating_fan_speed": "master_fan_speed",
    "humidity_control": "master_humidity",
    "humidity_setpoint": "master_humidity",
}
