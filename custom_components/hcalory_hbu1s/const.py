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

# Heater states (from notification data)
class HeaterState:
    OFF = 0x00
    STARTING = 0x01
    PREHEATING = 0x02
    RUNNING = 0x03
    SHUTDOWN = 0x04

    @classmethod
    def to_string(cls, state: int) -> str:
        mapping = {
            cls.OFF: "off",
            cls.STARTING: "starting",
            cls.PREHEATING: "preheating",
            cls.RUNNING: "running",
            cls.SHUTDOWN: "shutting_down",
        }
        return mapping.get(state, f"unknown_{state:02x}")

# Temperature limits
MIN_TEMP = 8
MAX_TEMP = 36
DEFAULT_TEMP = 16

# Connection settings
DISCONNECT_DELAY = 120
RETRY_COUNT = 3
RETRY_DELAY = 1.0
