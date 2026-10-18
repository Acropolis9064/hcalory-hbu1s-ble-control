"""Constants for the Hcalory HBU1S integration."""

DOMAIN = "hcalory_hbu1s"

# BLE UUIDs
SERVICE_UUID = "0000bd39-0000-1000-8000-00805f9b34fb"
WRITE_CHAR_UUID = "0000bdf7-0000-1000-8000-00805f9b34fb"
NOTIFY_CHAR_UUID = "0000bdf8-0000-1000-8000-00805f9b34fb"

# Protocol wrapper - all commands start with this
PROTOCOL_HEADER = bytes([0x00, 0x02, 0x00, 0x01, 0x00, 0x01, 0x00])

# Init command - must be sent after connecting to wake up heater
# This is the full command including header
CMD_INIT = bytes.fromhex("000200010001000a0c000005010000000012")

# Status query command - sent periodically to keep connection alive and get status
CMD_STATUS_QUERY = bytes.fromhex("000200010001000e040000090000000000000000000d")

# Command types
CMD_TYPE_POWER = 0x0e  # Power on/off
CMD_TYPE_TEMP = 0x07   # Set temperature (while running)

# Power commands (full inner command after header + length byte)
# Format: [length] [cmd_type] 04 00 00 09 00 00 00 00 00 00 00 00 00 [action] [checksum]
CMD_POWER_ON = bytes([0x0e, 0x04, 0x00, 0x00, 0x09, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02, 0x0f])
CMD_POWER_OFF = bytes([0x0e, 0x04, 0x00, 0x00, 0x09, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x01, 0x0e])

# Temperature command format (while running):
# Header: 00 02 00 01 00 01 00
# Inner:  07 06 00 00 02 [TEMP] 00 [CHECKSUM]
# Checksum = sum of inner bytes (06+00+00+02+temp+00) & 0xFF
CMD_TEMP_INNER_PREFIX = bytes([0x06, 0x00, 0x00, 0x02])

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
