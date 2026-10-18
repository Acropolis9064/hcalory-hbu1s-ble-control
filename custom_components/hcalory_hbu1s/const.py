"""Constants for the Hcalory HBU1S integration."""

DOMAIN = "hcalory_hbu1s"

# BLE UUIDs. The official app writes commands to bdf8, the same characteristic
# the status notifications come from (bdf7 is write-only and unused by the app).
SERVICE_UUID = "0000bd39-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000bdf8-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000bdf8-0000-1000-8000-00805f9b34fb"

# Protocol wrapper - all commands start with this
PROTOCOL_HEADER = bytes([0x00, 0x02, 0x00, 0x01, 0x00, 0x01, 0x00])


def build_command(body: bytes) -> bytes:
    """Build a full command: header, length, body, checksum.

    Length is len(body) + 1 and the checksum is the sum of the body bytes,
    e.g. power on = 0e | 04 00 00 09 00 00 00 00 00 00 00 00 02 | 0f.
    """
    return PROTOCOL_HEADER + bytes([len(body) + 1]) + body + bytes([sum(body) & 0xFF])


# Init command - must be sent after connecting to wake up heater
CMD_INIT = build_command(bytes([0x0c, 0x00, 0x00, 0x05, 0x01, 0x00, 0x00, 0x00, 0x00]))

# "Action" commands: 04 00 00 09, eight zero bytes, then the action code
ACTION_STATUS_QUERY = 0x00
ACTION_POWER_OFF = 0x01
ACTION_POWER_ON = 0x02
ACTION_AUTO_START_STOP_TOGGLE = 0x05
ACTION_MODE_TEMPERATURE = 0x06  # only accepted while the heater is on
ACTION_MODE_GEAR = 0x07  # only accepted while the heater is on


def action_command(action: int) -> bytes:
    """Build an action command (power, mode, status query...)."""
    return build_command(bytes([0x04, 0x00, 0x00, 0x09]) + bytes(8) + bytes([action]))


# Status query - sent periodically to keep the connection alive
CMD_STATUS_QUERY = action_command(ACTION_STATUS_QUERY)


def set_temperature_command(temp: int, fahrenheit: bool) -> bytes:
    """Build the set-temperature command; temp is in the heater's display units."""
    return build_command(bytes([0x06, 0x00, 0x00, 0x02, temp, 0x01 if fahrenheit else 0x00]))


# Not used by the integration, recorded for reference:
#   gear level:     build_command(07 00 00 01 [level])
#   display units:  build_command(0b 00 00 02 02 [01 = °F, 00 = °C])
#   (older versions of this integration sent the display-units command thinking
#   it selected temperature mode, which is why the heater stayed in gear mode)

# Status response header
STATUS_HEADER = bytes([0x00, 0x01, 0x00, 0x01])

# Status notification layout (43 bytes, message type 0x23 at byte 7).
# Mapped from Android HCI captures of the official app; see README.
STATUS_MSG_TYPE = 0x23
STATUS_MIN_LENGTH = 43
STATUS_IDX_MSG_TYPE = 7
STATUS_IDX_RUN_STATE = 20        # 0x00 standby, 0x8x on, 0x4x cooling down
STATUS_IDX_MODE = 21             # 0x01 temperature (thermostat), 0x02 gear (fixed level)
STATUS_IDX_SETPOINT = 22         # target temperature (display units) or gear level
STATUS_IDX_AUTO_START_STOP = 23  # 0x01 on, 0x02 off
STATUS_IDX_VOLTAGE = 24          # 2 bytes big-endian, tenths of a volt
STATUS_IDX_BODY_TEMP = 27        # 2 bytes big-endian signed, tenths of a degree (display units)
STATUS_IDX_AMBIENT_TEMP = 30     # 2 bytes big-endian signed, tenths of a degree (display units)
STATUS_IDX_UNIT = 37             # 0x01 Fahrenheit, 0x00 Celsius

MODE_TEMPERATURE = 0x01
MODE_GEAR = 0x02


class HeaterState:
    """Heater run state, decoded from status byte 20."""

    OFF = "off"
    STARTING = "starting"
    RUNNING = "running"
    COOLING_DOWN = "cooling_down"

    @classmethod
    def from_byte(cls, value: int) -> str:
        """Map the raw run-state byte to a state.

        Seen in captures: 0x80 -> 0x81 -> 0x83 while igniting and warming up,
        0x85 (briefly 0x87) once burning, 0x45 -> 0x43 -> 0x41 -> 0x42 while
        the fan cools the heater down after switch-off, and 0x00 in standby.
        """
        if value & 0x80:
            return cls.RUNNING if value in (0x85, 0x87) else cls.STARTING
        if value & 0x40:
            return cls.COOLING_DOWN
        return cls.OFF

# Temperature limits
MIN_TEMP = 8
MAX_TEMP = 36
DEFAULT_TEMP = 16

# Connection settings
DISCONNECT_DELAY = 120
RETRY_COUNT = 3
RETRY_DELAY = 1.0
POLL_INTERVAL = 5  # Seconds between status polls to keep connection alive
RECONNECT_INTERVAL = 30  # Seconds to wait after a failed reconnect before trying again
