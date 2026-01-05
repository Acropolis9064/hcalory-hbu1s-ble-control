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
    HeaterState,
    MIN_TEMP,
    MAX_TEMP,
    RETRY_COUNT,
    RETRY_DELAY,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class HeaterStatus:
    """Represents the current heater status."""
    
    state: int = HeaterState.OFF
    target_temp: int = 16
    body_temp: int = 0
    ambient_temp: int = 0
    connected: bool = False
    
    @property
    def is_on(self) -> bool:
        """Return True if heater is on."""
        return self.state not in (HeaterState.OFF, HeaterState.SHUTDOWN)
    
    @property
    def state_string(self) -> str:
        """Return human-readable state."""
        return HeaterState.to_string(self.state)


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
        """Parse status notification from heater.
        
        Packet format (43 bytes total) - properly mapped:
        Bytes 0-6: Header (00010001000100)
        Byte 7: Message type (0x23 for status)
        Bytes 8-10: 030000
        Byte 11: Stored target temperature (not used - unreliable when off)
        Bytes 12-19: ffff01f400000000
        Byte 20: Running indicator (0x00=off, 0x80/0x81/0x83=running, 0x42=transitioning)
        Byte 21: Power level (01)
        Byte 22: Current target temp (0x0f=15°C) - only valid when running
        Byte 23: Always 0x02
        Bytes 24+: Body temp and other data
        """
        if len(data) < 25:
            _LOGGER.debug("Status packet too short: %d bytes", len(data))
            return
        
        try:
            hex_data = data.hex()
            _LOGGER.debug("Parsing status: %s (len=%d)", hex_data, len(data))
            
            # Check for status message type (0x23 at byte 7)
            if len(data) > 7 and data[7] == 0x23:
                
                # Byte 20 indicates running state
                # 0x00 = off/standby, 0x80/0x81/0x83 = running, 0x42 = transitioning
                running_byte = data[20]
                old_state = self._status.state
                
                if running_byte == 0x00:
                    self._status.state = 0  # Off/Standby
                    # Don't update target_temp - keep last known value
                else:
                    self._status.state = 2  # Running (any non-zero value)
                    # Only update temp from byte 22 when running
                    self._status.target_temp = data[22]
                
                if old_state != self._status.state:
                    _LOGGER.info("Heater state changed: %d -> %d (running_byte=0x%02x)", 
                                old_state, self._status.state, running_byte)
                
                _LOGGER.debug("Parsed: running_byte=0x%02x, state=%d, target=%d°C", 
                             running_byte, self._status.state, self._status.target_temp)
            
        except Exception as err:
            _LOGGER.warning("Error parsing status: %s", err)
    
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
        """Turn the heater on using current target temperature."""
        _LOGGER.info("Turning heater ON at %d°C", self._status.target_temp)
        
        # Build power on command with current target temp
        # Format: 0e 04 00 00 09 00 00 00 00 00 00 00 00 02 [temp]
        temp = self._status.target_temp
        command = bytes([0x0e, 0x04, 0x00, 0x00, 0x09, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x02, temp])
        
        return await self._send_command(command)
    
    async def turn_off(self) -> bool:
        """Turn the heater off."""
        _LOGGER.info("Turning heater OFF")
        return await self._send_command(CMD_POWER_OFF)
    
    async def set_temperature(self, temp: int) -> bool:
        """Set target temperature (works while running).
        
        Args:
            temp: Target temperature in Celsius (8-36)
        """
        temp = max(MIN_TEMP, min(MAX_TEMP, temp))
        
        # Build temperature command
        # Inner: 06 00 00 02 [TEMP] 00 [CHECKSUM]
        inner = CMD_TEMP_INNER_PREFIX + bytes([temp, 0x00])
        checksum = sum(inner) & 0xFF
        
        # Full inner command with length byte
        command = bytes([0x07]) + inner + bytes([checksum])
        
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
