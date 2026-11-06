# Changelog

## 0.1.4 — 2026-11-06

- **Home Assistant 2026.11:** the climate entity provides the native
  temperature API (`native_current_temperature`, `native_target_temperature`,
  `_attr_native_temperature_unit`), so 2026.11 no longer warns that it stops
  working in 2027.11. The old names stay as aliases for the releases before
  2026.11.

## 0.1.3 — 2026-11-04

- **Valve off the Security view:** `binary_sensor.fancoil_valve_open` no
  longer has the "opening" device class. Home Assistant's Security view lists
  every binary sensor of that class, so it showed the water valve as if it were
  a door. It still reads Open or Closed, from its own translations.

## 0.1.2 — 2026-10-30

- **Mode, not winter:** coil 1 and discrete input 1, the manual's
  summer/winter, are now named for what they do. With writes on, the
  "Winter mode (heating)" switch is a select, `select.fancoil_mode`: Heating or
  Cooling. The status is a sensor, `sensor.fancoil_mode_in_use`, and the command
  read-only is `sensor.fancoil_mode`. The consent is "Mode from master"
  (`switch.fancoil_master_mode`).
- **Upgrading from 0.1.x:** the old entities (`switch.fancoil_winter_mode`,
  `binary_sensor.fancoil_winter`, `binary_sensor.fancoil_winter_mode`,
  `*.fancoil_master_winter_mode`) are removed from the registry. Automations
  that used them need the new ids: `switch.turn_on` on the winter switch becomes
  `select.select_option` with `heating`.

## 0.1.1 — 2026-10-30

- **Probed:** the reference unit read in full on 2026-10-30, kept as
  `tests/fixtures/fwecsa_capture.json`. The tests run the integration against
  it: 4 speeds, 2 pipes, on/off valve, switching on water temperature, and a
  cooling setpoint the unit holds as −921.6 °C shown as unknown.
- **Simulator:** answers as the unit did. Setpoints in use are held to their
  limits, the anti-freeze input no longer copies its enable coil, and with
  switching on water or air the season no longer follows the coil.
- **Docs:** what the probe settled and what it left open.

## 0.1.0 — 2026-10-29

First release: every variable in the FWECSA manual (FC66003946 Rev 00) as an
entity, read-only by default.

- **Reads** all four tables, one request each, every 10 s: 18 coils, 31
  discrete inputs, 12 holding registers, 15 input registers. A table the unit
  refuses to read whole is read one value at a time from then on.
- **Climate entity** from the unit's own status: on/off, heating or cooling,
  room temperature and humidity, the setpoint in use, and what it is doing.
- **Writes (opt-in):** a switch per coil, a number per holding register, the
  fan speed as a select, and the climate entity's commands. FC15/FC16 only;
  each write is skipped if already so, read back, rate limited, and an
  unapplied one names its consent coil when that is off.
- **Summer/winter switching** option, mirroring the unit's parameter: it picks
  the setpoint register the climate entity writes and the modes it offers.
- **Links:** USB/RS-485 adapter, Modbus TCP gateway (mbusd), or RTU over TCP.
  Entries on one link share one serialised bus. Reconfigure changes the link in
  place.
- **Support:** diagnostics with raw values, an admin `read_registers` action,
  a read-only probe (`tools/probe_fwecsa.py`) and a simulator
  (`tools/sim_fwecsa.py`). English and Ukrainian.
- **Icon:** Daikin's mark in `brand/` (256 and 512 px, transparent), so the
  integrations page and HACS show it.

Verified on the reference unit (FWB15CTV, slave 1, behind mbusd): addressing,
temperature scale, summer/winter polarity. Not yet: humidity and percentage
scales, the two-way configuration bits, the consent coils' effect.
