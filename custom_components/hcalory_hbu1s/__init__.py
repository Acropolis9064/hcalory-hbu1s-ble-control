"""The Hcalory HBU1S integration."""
from __future__ import annotations

import logging
import asyncio

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import ADDRESS, BluetoothCallbackMatcher
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, POLL_INTERVAL
from .client import HcaloryBleClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hcalory HBU1S from a config entry."""
    address: str = entry.data[CONF_ADDRESS]
    
    # Get the BLE device
    ble_device = bluetooth.async_ble_device_from_address(
        hass, address.upper(), connectable=True
    )
    
    if not ble_device:
        raise ConfigEntryNotReady(f"Could not find Hcalory device with address {address}")
    
    # Create client
    client = HcaloryBleClient(ble_device)
    
    # Try to connect
    if not await client.connect():
        raise ConfigEntryNotReady(f"Could not connect to Hcalory device {address}")
    
    # Start polling task to keep connection alive
    async def poll_status():
        """Poll heater status periodically to keep connection alive."""
        while True:
            try:
                await asyncio.sleep(POLL_INTERVAL)
                if client.is_connected:
                    await client.request_status()
                else:
                    _LOGGER.debug("Not connected, attempting reconnect")
                    await client.connect()
            except Exception as err:
                _LOGGER.warning("Poll error: %s", err)
    
    poll_task = asyncio.create_task(poll_status())
    
    # Store client and poll task
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "poll_task": poll_task,
    }
    
    # Register callback for device updates
    @callback
    def _async_update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Update from a BLE callback."""
        client.set_ble_device(service_info.device)
    
    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            BluetoothCallbackMatcher({ADDRESS: address}),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )
    
    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)
        
        # Cancel poll task
        poll_task = data.get("poll_task")
        if poll_task:
            poll_task.cancel()
            try:
                await poll_task
            except asyncio.CancelledError:
                pass
        
        client: HcaloryBleClient = data["client"]
        await client.disconnect()
    
    return unload_ok
