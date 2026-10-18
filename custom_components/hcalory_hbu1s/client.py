"""BLE client for Hcalory HBU1S heater communication."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable

from bleak import BleakClient
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from .const import (
    SERVICE_UUID,
    WRITE_CHAR_UUID,
    NOTIFY_CHAR_UUID,
    PROTOCOL_HEADER,
    CMD_POWER_ON,
    CMD_POWER_OFF,
    CMD_TEMP_INNER_PREFIX,
    CMD_INIT,
    CMD_STATUS_QUERY,
    DEFAULT_TEMP,
    HeaterState,
    MIN_TEMP,
    MAX_TEMP,
    MODE_GEAR,
    MODE_TEMPERATURE,
    RETRY_COUNT,
    RETRY_DELAY,
    STATUS_IDX_AMBIENT_TEMP,
    STATUS_IDX_AUTO_START_STOP,
    STATUS_IDX_BODY_TEMP,
    STATUS_IDX_MODE,
    STATUS_IDX_MSG_TYPE,
    STATUS_IDX_RUN_STATE,
    STATUS_IDX_SETPOINT,
    STATUS_IDX_UNIT,
    STATUS_IDX_VOLTAGE,
    STATUS_MIN_LENGTH,
    STATUS_MSG_TYPE,
)

_LOGGER = logging.getLogger(__name__)


def _tenths_to_celsius(raw: int, fahrenheit: bool) -> float:
    """Convert a tenths-of-a-degree reading in the heater's display units to °C."""
    value = raw / 10
    if fahrenheit:
        value = (value - 32) * 5 / 9
    return round(value, 1)


@dataclass
class HeaterStatus:
    """Represents the current heater status.

    Temperatures are always in °C here, whatever units the heater displays.
    """

    state: str = HeaterState.OFF
    run_byte: int = 0
    mode: int | None = None  # MODE_TEMPERATURE or MODE_GEAR (only reported while on)
    setpoint: int | None = None  # raw: target in display units, or gear level
    fahrenheit: bool = False  # heater display units
    auto_start_stop: bool | None = None
    voltage: float | None = None
    body_temp: float | None = None
    ambient_temp: float | None = None
    target_temp: int = DEFAULT_TEMP  # °C, last reported or requested
    connected: bool = False

    @property
    def is_on(self) -> bool:
        """Return True if the heater is starting or running."""
        return self.state in (HeaterState.STARTING, HeaterState.RUNNING)

    @property
    def gear_level(self) -> int | None:
        """Return the gear level while running in gear mode."""
        return self.setpoint if self.mode == MODE_GEAR else None


class HcaloryBleClient:
    """BLE client for communicating with Hcalory HBU1S heater."""
    
    def __init__(
        self,
        ble_device: BLEDevice,
        status_callback: Callable[[HeaterStatus], None] | None = None,
    ) -> None:
        """Initialize the client."""
        self._ble_device = ble_device
        self._client: BleakClient | None = None
        self._status = HeaterStatus()
        self._status_callback = status_callback
        self._connect_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
    
    @property
    def is_connected(self) -> bool:
        """Return True if connected to heater."""
        return self._client is not None and self._client.is_connected
    
    @property
    def status(self) -> HeaterStatus:
        """Return current heater status."""
        return self._status
    
    def set_ble_device(self, ble_device: BLEDevice) -> None:
        """Update the BLE device reference."""
        self._ble_device = ble_device
    
    async def connect(self) -> bool:
        """Connect to the heater."""
        async with self._connect_lock:
            if self.is_connected:
                return True
            
            try:
                self._client = BleakClient(
                    self._ble_device,
                    disconnected_callback=self._on_disconnect,
                )
                await self._client.connect()
                
                # Subscribe to notifications
                await self._client.start_notify(
                    NOTIFY_CHAR_UUID,
                    self._on_notification,
                )
                
                # Send init command to wake up heater
                _LOGGER.debug("Sending init command to heater")
                await self._client.write_gatt_char(
                    WRITE_CHAR_UUID,
                    CMD_INIT,
                    response=False,
                )
                
                # Give heater time to respond
                await asyncio.sleep(0.5)
                
                self._status.connected = True
                _LOGGER.info("Connected to heater: %s", self._ble_device.address)
                return True
                
            except BleakError as err:
                _LOGGER.error("Failed to connect: %s", err)
                self._status.connected = False
                return False
    
    async def disconnect(self) -> None:
        """Disconnect from the heater."""
        if self._client:
            try:
                await self._client.disconnect()
            except BleakError as err:
                _LOGGER.warning("Error during disconnect: %s", err)
            finally:
                self._client = None
                self._status.connected = False
    
    def _on_disconnect(self, client: BleakClient) -> None:
        """Handle disconnection."""
        _LOGGER.info("Heater disconnected")
        self._status.connected = False
        if self._status_callback:
            self._status_callback(self._status)
    
    def _on_notification(self, sender: int, data: bytearray) -> None:
        """Handle incoming notification data."""
        _LOGGER.debug("Notification received: %s", data.hex())
        self._parse_status(data)
        if self._status_callback:
            self._status_callback(self._status)
    
    def _parse_status(self, data: bytearray) -> None:
        """Parse a status notification from the heater.

        43-byte packet, message type 0x23 at byte 7. Field positions are in
        const.py (STATUS_IDX_*) and documented in the README. Temperatures are
        tenths of a degree in the heater's display units (byte 37 says which)
        and are converted to °C here. Mode and setpoint are only reported
        while the heater is on (they read 0 in standby).
        """
        if len(data) < STATUS_MIN_LENGTH or data[STATUS_IDX_MSG_TYPE] != STATUS_MSG_TYPE:
            _LOGGER.debug("Ignoring non-status packet: %s", data.hex())
            return

        status = self._status
        old_state = status.state

        status.run_byte = data[STATUS_IDX_RUN_STATE]
        status.state = HeaterState.from_byte(status.run_byte)
        status.fahrenheit = data[STATUS_IDX_UNIT] == 0x01
        status.auto_start_stop = data[STATUS_IDX_AUTO_START_STOP] == 0x01
        status.voltage = int.from_bytes(data[STATUS_IDX_VOLTAGE:STATUS_IDX_VOLTAGE + 2], "big") / 10
        status.body_temp = _tenths_to_celsius(
            int.from_bytes(data[STATUS_IDX_BODY_TEMP:STATUS_IDX_BODY_TEMP + 2], "big", signed=True),
            status.fahrenheit,
        )
        status.ambient_temp = _tenths_to_celsius(
            int.from_bytes(data[STATUS_IDX_AMBIENT_TEMP:STATUS_IDX_AMBIENT_TEMP + 2], "big", signed=True),
            status.fahrenheit,
        )

        if status.is_on:
            status.mode = data[STATUS_IDX_MODE]
            status.setpoint = data[STATUS_IDX_SETPOINT]
            if status.mode == MODE_TEMPERATURE and status.setpoint:
                target = status.setpoint
                if status.fahrenheit:
                    target = round((target - 32) * 5 / 9)
                status.target_temp = max(MIN_TEMP, min(MAX_TEMP, target))
        else:
            status.mode = None
            status.setpoint = None

        if old_state != status.state:
            _LOGGER.info("Heater state: %s -> %s (0x%02x)", old_state, status.state, status.run_byte)

        _LOGGER.debug(
            "Status: state=%s mode=%s setpoint=%s unit=%s ambient=%s°C body=%s°C voltage=%sV",
            status.state,
            status.mode,
            status.setpoint,
            "F" if status.fahrenheit else "C",
            status.ambient_temp,
            status.body_temp,
            status.voltage,
        )
    
    async def _send_command(self, command: bytes) -> bool:
        """Send a command to the heater."""
        async with self._operation_lock:
            for attempt in range(RETRY_COUNT):
                try:
                    if not self.is_connected:
                        if not await self.connect():
                            continue
                    
                    # Build full command with protocol header
                    full_command = PROTOCOL_HEADER + command
                    
                    _LOGGER.debug("Sending command: %s", full_command.hex())
                    
                    await self._client.write_gatt_char(
                        WRITE_CHAR_UUID,
                        full_command,
                        response=False,
                    )
                    return True
                    
                except BleakError as err:
                    _LOGGER.warning(
                        "Command failed (attempt %d/%d): %s",
                        attempt + 1,
                        RETRY_COUNT,
                        err,
                    )
                    await asyncio.sleep(RETRY_DELAY)
            
            return False
    
    async def turn_on(self) -> bool:
        """Turn the heater on in thermostat mode."""
        _LOGGER.info("Turning heater ON")
        
        # Power ON command: 0e 04 00 00 09 00 00 00 00 00 00 00 00 02 0f
        # Last byte is checksum: action (0x02) + 0x0d = 0x0f
        on_command = bytes([0x0e, 0x04, 0x00, 0x00, 0x09, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02, 0x0f])
        
        success = await self._send_command(on_command)
        if not success:
            return False
        
        # Wait 2 seconds for heater to process the ON command
        await asyncio.sleep(2.0)
        
        # Switch to thermostat mode: 07 0b 00 00 02 02 00 0f
        _LOGGER.info("Switching to thermostat mode")
        mode_command = bytes([0x07, 0x0b, 0x00, 0x00, 0x02, 0x02, 0x00, 0x0f])
        
        return await self._send_command(mode_command)
    
    async def turn_off(self) -> bool:
        """Turn the heater off."""
        _LOGGER.info("Turning heater OFF")
        return await self._send_command(CMD_POWER_OFF)
    
    async def set_temperature(self, temp: int) -> bool:
        """Set target temperature (works while running in thermostat mode).
        
        Args:
            temp: Target temperature in Celsius (8-36)
        """
        temp = max(MIN_TEMP, min(MAX_TEMP, temp))
        
        # Temperature command: 07 06 00 00 02 [temp] 00 [checksum]
        # Checksum = sum of bytes 1-6
        payload = bytes([0x06, 0x00, 0x00, 0x02, temp, 0x00])
        checksum = sum(payload) & 0xFF
        command = bytes([0x07]) + payload + bytes([checksum])
        
        _LOGGER.info("Setting temperature to %d°C", temp)
        
        success = await self._send_command(command)
        if success:
            self._status.target_temp = temp
        
        return success

    async def request_status(self) -> bool:
        """Send status request to keep connection alive and get current state."""
        # Send the status query command (different from init)
        try:
            if not self.is_connected:
                return False
            
            await self._client.write_gatt_char(
                WRITE_CHAR_UUID,
                CMD_STATUS_QUERY,
                response=False,
            )
            _LOGGER.debug("Status query sent")
            return True
        except BleakError as err:
            _LOGGER.warning("Status request failed: %s", err)
            return False
