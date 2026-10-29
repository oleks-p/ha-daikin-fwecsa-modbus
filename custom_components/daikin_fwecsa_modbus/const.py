"""Constants for the Daikin FWECSA integration."""

from __future__ import annotations

from typing import Final

from homeassistant.const import Platform

DOMAIN: Final = "daikin_fwecsa_modbus"
MANUFACTURER: Final = "Daikin"
MODEL: Final = "FWECSA"
DEFAULT_NAME: Final = "Fancoil"

PLATFORMS: Final = [Platform.SENSOR, Platform.BINARY_SENSOR, Platform.CLIMATE, Platform.NUMBER,
                     Platform.SELECT, Platform.SWITCH]

# -- connection ---------------------------------------------------------------

CONF_TRANSPORT: Final = "transport"
CONF_SERIAL_PORT: Final = "serial_port"
CONF_BAUDRATE: Final = "baudrate"
CONF_SLAVE: Final = "slave"
CONF_ENTITY_PREFIX: Final = "entity_prefix"

TRANSPORT_SERIAL: Final = "serial"
# A transparent serial server: raw RTU frames over a TCP socket.
TRANSPORT_RTU_OVER_TCP: Final = "rtu_over_tcp"
# A Modbus-TCP gateway (mbusd, most commercial ones): MBAP framing, the gateway
# speaks RTU on the bus.
TRANSPORT_TCP: Final = "tcp"
TRANSPORTS: Final = (TRANSPORT_SERIAL, TRANSPORT_RTU_OVER_TCP, TRANSPORT_TCP)

#: The manual: "settable baudrate (default: 9600)", always 8N1.
DEFAULT_BAUDRATE: Final = 9600
DEFAULT_TCP_PORT: Final = 502
#: "Serial address = set a value between 1 and 255"; the reference unit uses 1.
DEFAULT_SLAVE: Final = 1
DEFAULT_ENTITY_PREFIX: Final = "fancoil"

#: Response timeout. Longer than a gateway's own retries: mbusd on the reference
#: bus waits 500 ms and tries three times before it answers "target failed to
#: respond" (exception 11). A client that gives up first reads that late answer
#: as the reply to its next request -- which is how Home Assistant's YAML modbus
#: hub, at 1 s, lost this unit on the reference bus.
REQUEST_TIMEOUT: Final = 3.0
#: Quiet time between frames on the bus.
FRAME_GAP: Final = 0.050
#: Pause after a failed exchange before the link is used again, so a late reply
#: dies with the old connection instead of answering the next request.
RESYNC_DELAY: Final = 1.0

#: All four tables are read every poll: four requests, about 0.3 s at 9600 baud.
POLL_INTERVAL: Final = 10

# -- options ------------------------------------------------------------------

#: How long the link may fail before entities go unavailable.
CONF_UNAVAILABLE_AFTER: Final = "unavailable_after"
DEFAULT_UNAVAILABLE_AFTER: Final = 60
MIN_UNAVAILABLE_AFTER: Final = 20
MAX_UNAVAILABLE_AFTER: Final = 900

#: Off by default: the integration only reads until this is turned on.
CONF_ALLOW_WRITES: Final = "allow_writes"

#: Mirrors the unit's own configuration parameter "Switching Summer/Winter"
#: (CONFIGURATION MENU, password 10). Modbus cannot read it, and it decides
#: which setpoint register is live and whether Home Assistant may choose
#: heating or cooling at all.
CONF_SWITCHING: Final = "switching"
SWITCHING_KEYBOARD: Final = "keyboard"            # "From keyboard/serial" (factory default)
SWITCHING_DIGITAL_INPUT: Final = "digital_input"  # "From Digital input"
SWITCHING_AUTO_WATER: Final = "auto_water"        # "Auto on water temp."
SWITCHING_AUTO_AIR: Final = "auto_air"            # "Auto on air temp."
SWITCHINGS: Final = (SWITCHING_KEYBOARD, SWITCHING_DIGITAL_INPUT, SWITCHING_AUTO_WATER,
                     SWITCHING_AUTO_AIR)
AUTO_SWITCHINGS: Final = frozenset({SWITCHING_AUTO_WATER, SWITCHING_AUTO_AIR})
DEFAULT_SWITCHING: Final = SWITCHING_KEYBOARD

# -- writes (opt-in) ------------------------------------------------------------

#: A register is written at most once per this many seconds ...
WRITE_MIN_INTERVAL: Final = 3.0
#: ... and the unit at most this many times a day. The controller keeps its
#: settings across a power cut, so they live in non-volatile memory; this stops
#: a runaway automation from wearing it out, not a person using the thermostat.
WRITE_DAILY_LIMIT: Final = 200
EVENT_WRITTEN: Final = f"{DOMAIN}_written"
SERVICE_READ_REGISTERS: Final = "read_registers"
