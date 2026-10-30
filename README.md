# Daikin FWECSA fancoil for Home Assistant (Modbus RTU)

A config-flow integration for Daikin hydronic fancoils (FWB, FWV, FWL…) fitted
with the **FWECSA** controller. It talks to the controller's RS-485 port
(terminals **A/B/GND** on the I/O board), either through a network gateway such
as mbusd, or from a USB adapter on the Home Assistant host.

It reads every variable the manual lists: 18 coils, 31 discrete inputs, 12
holding registers and 15 input registers. **Writes are opt-in:** with *Allow
writes* on, the coils and holding registers become switches, numbers and a
select, and the climate entity can switch the unit and set its target. Every
write is read back. The unit's own controller still runs the fan and the valve.

Not affiliated with Daikin.

## Status

The integration is built from the manual (FC66003946 Rev 00) and checked
against the reference unit (an FWB15CTV, slave 1, behind mbusd), which [the probe](#probe)
read in full on 2026-10-30 (`tests/fixtures/fwecsa_capture.json`; the tests run
the integration against it). Confirmed there:

- the addressing (manual number − 1), and that a table read whole gives the
  same values as reading it one at a time;
- temperatures in signed tenths of a degree, and the unit holding a setpoint
  to its limits: a cooling setpoint of −921.6 °C in holding 1 is in use as
  10.0 °C, its minimum;
- summer/winter (1 = winter), and switching on water temperature leaving the
  summer/winter coil out of it;
- humidity setpoints in whole percent (limits 35 and 75);
- discrete input 11 (0 = 2 pipes) and 28 (1 = automatic fan).

Not yet checked on a unit:

- room humidity and the analogue outputs (no humidity probe; outputs idle);
- discrete inputs 10, 12 and 13 (speeds, fan type, regulation probe): the
  reference unit reads 4 speeds, step fan, board probe, which nothing else
  confirms;
- the consent coils' exact effect (see [Writes](#writes-opt-in)). The probe
  only reads; on the reference unit every consent is off.

## What you get

- **Climate entity** (`climate.fancoil`): room temperature, humidity (with a
  humidity probe), the setpoint in use, on/off and heating/cooling from the
  unit's own status, and what it is doing — heating, cooling, fan only,
  drying, idle. With writes on: off/heat/cool (or off/auto), target
  temperature, fan speed (step fans) and the Economy preset.
- **Sensors** for every input register and, read-only, every holding register:
  room, water and hot-water temperature, fan status, setpoints and their limits,
  fan speed, modulating fan and analogue outputs, valve type. The mode — the
  manual's summer/winter — is a sensor too, heating or cooling: the mode in use
  (`sensor.fancoil_mode_in_use`) and the command (`sensor.fancoil_mode`).
- **Binary sensors** for every other discrete input — unit on, economy,
  anti-freeze, the alarm and each probe alarm, valve open, dehumidifying,
  heater, outputs O1–O7, and how the unit is built (speeds, pipes, fan type,
  probes, heaters, valve) — and, read-only, every other coil.
- **With *Allow writes*:** a switch per coil, a number per holding register,
  and two selects: the mode (`select.fancoil_mode`, heating or cooling) and the
  fan speed.
- **Link health:** last successful read and read failures. Short outages keep
  the last values; entities go unavailable after 60 s without an answer
  (configurable).
- **Languages:** English and Ukrainian.

Entities for parts the unit reports it does not have (a humidity probe, a
4-pipe hot-water circuit, a modulating fan, heaters) exist but start disabled.

Every variable, with its address and entity ids: [docs/register_map.md](docs/register_map.md).

## Before you start

**One master on the bus.** If the fancoil shares its RS-485 pair with anything
else Home Assistant polls — a heat pump, a wall panel — put a Modbus TCP gateway
such as [mbusd](https://github.com/3cky/mbusd) in front of the bus and connect
every integration through it. A serial port opens once, and two masters on one
pair collide.

**Set the unit up as a supervisor slave.** On the FWECSA: PRG → *Networks and
connections* (password 20) → SETUP RS485:

- MST/SLV = **Slave from SPV**
- Protocol = **Modbus**
- Serial address = unique on the bus, 1–247
- Speed = the bus's baud rate (factory 9600; always 8N1)

Leave SETUP OC at MST/SLV = none.

## Install

Add this repository to HACS as a custom repository (category *Integration*), or
copy `custom_components/daikin_fwecsa_modbus` into your Home Assistant
`config/custom_components/`. Restart.

## Configure

*Settings → Devices & services → Add integration → Daikin FWECSA fancoil*:

- **Network gateway** — host, port, gateway type and Modbus address. mbusd
  speaks *Modbus TCP*; choose *RTU over TCP* only for a transparent serial
  server. Example: mbusd on the Home Assistant host at `127.0.0.1:10502`,
  Modbus TCP, address 1.
- **USB / RS-485 adapter** — port (prefer `/dev/serial/by-id/…`), baud rate and
  address.

The **entity ID prefix** (default `fancoil`) starts every entity id:
`climate.fancoil`, `sensor.fancoil_room_temperature`. Use a different prefix
for each fancoil.

*Reconfigure* changes the link — including from serial to a gateway — while
keeping the entry, its entity ids and their history.

### Options

- **Allow writes** — off by default.
- **Summer/winter switching on the unit** — must match the unit's parameter
  *Switching Summer/Winter* (PRG → configuration menu, password 10), which
  Modbus cannot read:

  | Unit setting | Climate offers | Target temperature writes |
  |---|---|---|
  | From keyboard/serial (factory) | off, heat, cool | holding 1 (cooling) or 4 (heating), by season |
  | From digital input | off, and the season the contact sets | the same |
  | Auto on water / air temp. | off, auto | holding 7, the single setpoint |

- **Unavailable after** — how long the link may fail before entities show as
  unavailable.

## Writes (opt-in)

Writes use FC15 (coils) and FC16 (holding registers) only: the FWECSA does not
answer FC5 or FC6. A Home Assistant `modbus:` YAML setup needs
`write_type: coils` and `write_registers: true` for the same reason.

Every write reads the value first and skips it if it is already set, then
writes it, reads it back, and fires `daikin_fwecsa_modbus_written`. A register
is written at most once every 3 s, and the unit at most 200 times a day.

**Consent coils.** For each function there is an *enable … from MASTER* coil
(coils 7–14 and 16). The unit may ignore Modbus for a function whose consent is
off and keep following its keyboard, without an error. If a write is
acknowledged but not kept and its consent coil is off, the error names that
coil. The integration does not switch consents on by itself; switch them on
(they are switches under *Configuration* with writes on) for what Home
Assistant should control.

**When Home Assistant goes away**, the unit does what its parameter *ON/OFF and
SUM/WIN with disconnected serial* says: back to the keyboard (factory), or hold
the supervisor's last settings.

## Replacing a YAML modbus setup

1. Remove the fancoil's entities from your `modbus:` YAML (keep anything else
   on the hub) and restart, so their entity ids are free.
2. Add the integration with the same prefix the YAML entities used. Ids that
   match carry their history over: `climate.fancoil`, `switch.fancoil_power`,
   `sensor.fancoil_water_temperature`, `binary_sensor.fancoil_valve_open`,
   `binary_sensor.fancoil_alarm`.

On a bus behind mbusd, a YAML hub needs a timeout longer than mbusd's own
retries (`-W` × (`-N` + 1)); otherwise late answers are matched to the wrong
requests and every device on the hub drops out. This integration waits 3 s.

## Actions

`daikin_fwecsa_modbus.read_registers` (admin only) reads raw values from one
table through the integration's own connection: *table*, and optionally
*address* (from 0) and *count*. Without an address it reads the whole table.

## Probe

`tools/probe_fwecsa.py` reads every documented variable once — FC1–4 only,
never a write — and saves a capture whose `tables` have the same shape as the
test fixture. Through a gateway it can run alongside the integration:

```sh
python3 tools/probe_fwecsa.py --tcp 127.0.0.1:10502 --slave 1 -o capture.json
```

Python 3.11 and pymodbus. To run it inside the Home Assistant container, which
has both: `docker exec -i homeassistant python3 - --tcp 127.0.0.1:10502 < tools/probe_fwecsa.py`.

## Development

```sh
python3.14 -m venv .venv && .venv/bin/pip install -r requirements_test.txt
.venv/bin/ruff check custom_components tools tests
.venv/bin/pytest -q
```

Translations are generated from `tools/gen_translations.py`, and
`docs/register_map.md` from `tools/gen_docs.py`; tests fail if either is stale.
`docker compose up -d` starts a development Home Assistant against the
simulator (host `sim`, port 5020, Modbus TCP, address 1).

## License

MIT.
