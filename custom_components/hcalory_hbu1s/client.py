"""BLE client for Hcalory HBU1S heater communication."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable

from bleak.backends.device import BLEDevice
from bleak.exc import BleakError
from bleak_retry_connector import (
    BleakClientWithServiceCache,
    establish_connection,
)

from .const import (
    ACTION_MODE_TEMPERATURE,
    ACTION_POWER_OFF,
    ACTION_POWER_ON,
    WRITE_CHAR_UUID,
    NOTIFY_CHAR_UUID,
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
    action_command,
    set_temperature_command,
)

# How long to wait for the heater to confirm a change in its status updates
CONFIRM_TIMEOUT = 10.0

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
        ble_device_callback: Callable[[], BLEDevice | None] | None = None,
    ) -> None:
        """Initialize the client.

        ble_device_callback should return the freshest BLEDevice Home Assistant
        knows about, so each (re)connect can go through whichever Bluetooth
        adapter or proxy currently has the best signal and a free slot.
        """
        self._ble_device = ble_device
        self._ble_device_callback = ble_device_callback
        self._client: BleakClientWithServiceCache | None = None
        self._status = HeaterStatus()
        self._status_callback = status_callback
        self._connect_lock = asyncio.Lock()
        self._operation_lock = asyncio.Lock()
        self._status_event = asyncio.Event()

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

    def _latest_ble_device(self) -> BLEDevice:
        """Return the most recent BLEDevice for the heater."""
        if self._ble_device_callback and (device := self._ble_device_callback()):
            self._ble_device = device
        return self._ble_device

    async def connect(self) -> bool:
        """Connect to the heater (only ever one connection at a time)."""
        async with self._connect_lock:
            if self.is_connected:
                return True

            # Drop any half-open previous connection before making a new one
            await self._close_client()

            device = self._latest_ble_device()
            try:
                client = await establish_connection(
                    BleakClientWithServiceCache,
                    device,
                    device.name or device.address,
                    disconnected_callback=self._on_disconnect,
                    max_attempts=3,
                    ble_device_callback=self._latest_ble_device,
                )
                self._client = client
                await client.start_notify(NOTIFY_CHAR_UUID, self._on_notification)

                # Init command wakes the heater up and starts status updates
                _LOGGER.debug("Sending init command to heater")
                await client.write_gatt_char(WRITE_CHAR_UUID, CMD_INIT, response=False)
                await asyncio.sleep(0.5)
            except (BleakError, asyncio.TimeoutError) as err:
                _LOGGER.warning("Could not connect to heater: %s", err)
                await self._close_client()
                return False

            self._status.connected = True
            _LOGGER.info("Connected to heater %s", device.address)
            return True

    async def disconnect(self) -> None:
        """Disconnect from the heater."""
        async with self._connect_lock:
            await self._close_client()

    async def _close_client(self) -> None:
        """Disconnect and forget the current client, if any."""
        client, self._client = self._client, None
        self._status.connected = False
        if client is not None:
            try:
                await client.disconnect()
            except BleakError as err:
                _LOGGER.debug("Error during disconnect: %s", err)

    def _on_disconnect(self, client: BleakClientWithServiceCache) -> None:
        """Handle the heater dropping the connection."""
        if self._client is not None and client is not self._client:
            return  # an older connection we already replaced
        _LOGGER.info("Heater disconnected")
        self._status.connected = False
        if self._status_callback:
            self._status_callback(self._status)
    
    def _on_notification(self, sender: int, data: bytearray) -> None:
        """Handle incoming notification data."""
        _LOGGER.debug("Notification received: %s", data.hex())
        self._parse_status(data)
        self._status_event.set()
        if self._status_callback:
            self._status_callback(self._status)

    async def _wait_for(self, condition: Callable[[], bool], timeout: float) -> bool:
        """Wait until the heater's status updates satisfy condition."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while not condition():
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            self._status_event.clear()
            try:
                await asyncio.wait_for(self._status_event.wait(), remaining)
            except asyncio.TimeoutError:
                return condition()
        return True
    
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
        """Send a full command (built with const.build_command) to the heater."""
        async with self._operation_lock:
            for attempt in range(RETRY_COUNT):
                try:
                    if not self.is_connected:
                        if not await self.connect():
                            continue

                    _LOGGER.debug("Sending command: %s", command.hex())

                    await self._client.write_gatt_char(
                        WRITE_CHAR_UUID,
                        command,
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
    
    async def turn_on(self, target_temp: int | None = None) -> bool:
        """Turn the heater on in temperature (thermostat) mode.

        The heater powers on in whichever mode it was last used in (gear or
        temperature) and only accepts a mode change while it is on. So: power
        on, wait until it reports it is on, switch to temperature mode if
        needed, then send the target temperature.

        Args:
            target_temp: Target in °C; defaults to the last known target.
        """
        target = max(MIN_TEMP, min(MAX_TEMP, target_temp or self._status.target_temp))
        _LOGGER.info("Turning heater ON (target %d°C)", target)

        if not self._status.is_on:
            if not await self._send_command(action_command(ACTION_POWER_ON)):
                return False
            if not await self._wait_for(lambda: self._status.is_on, CONFIRM_TIMEOUT):
                _LOGGER.warning("Heater did not report that it turned on")
                return False

        return await self._apply_temperature_mode(target)

    async def turn_off(self) -> bool:
        """Turn the heater off (it then runs its fan to cool down)."""
        _LOGGER.info("Turning heater OFF")
        return await self._send_command(action_command(ACTION_POWER_OFF))

    async def set_temperature(self, temp: int) -> bool:
        """Set the target temperature in °C.

        If the heater is on it is switched to temperature mode (if it was in
        gear mode) and given the new target. If it is off, the target is kept
        and applied the next time it is turned on.
        """
        target = max(MIN_TEMP, min(MAX_TEMP, temp))
        _LOGGER.info("Setting target temperature to %d°C", target)
        if not self._status.is_on:
            self._status.target_temp = target
            return True
        return await self._apply_temperature_mode(target)

    async def _apply_temperature_mode(self, target: int) -> bool:
        """Make sure a running heater is in temperature mode at target °C."""
        status = self._status
        if status.mode != MODE_TEMPERATURE:
            _LOGGER.info("Switching heater to temperature mode")
            for _ in range(2):
                if not await self._send_command(action_command(ACTION_MODE_TEMPERATURE)):
                    return False
                if await self._wait_for(lambda: status.mode == MODE_TEMPERATURE, CONFIRM_TIMEOUT):
                    break
            else:
                _LOGGER.warning("Heater did not switch to temperature mode")
                return False

        # The set-temperature command uses the heater's display units
        value = round(target * 9 / 5 + 32) if status.fahrenheit else target
        if status.setpoint != value:
            if not await self._send_command(set_temperature_command(value, status.fahrenheit)):
                return False
        status.target_temp = target
        return True

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
