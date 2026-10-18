"""The Hcalory HBU1S integration."""
from __future__ import annotations

import logging
import asyncio

from bleak.backends.device import BLEDevice

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.match import ADDRESS, BluetoothCallbackMatcher
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ADDRESS, Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, POLL_INTERVAL, RECONNECT_INTERVAL
from .client import HcaloryBleClient

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Hcalory HBU1S from a config entry."""
    address: str = entry.data[CONF_ADDRESS].upper()

    @callback
    def _latest_ble_device() -> BLEDevice | None:
        """Return the freshest connectable BLEDevice HA has for the heater."""
        return bluetooth.async_ble_device_from_address(hass, address, connectable=True)

    ble_device = _latest_ble_device()
    if not ble_device:
        # The heater stops advertising while another device (e.g. the Hcalory
        # app) is connected to it; HA retries setup automatically.
        raise ConfigEntryNotReady(
            f"Hcalory heater {address} not found (powered off, out of range, "
            "or connected to the Hcalory app?)"
        )

    client = HcaloryBleClient(ble_device, ble_device_callback=_latest_ble_device)

    if not await client.connect():
        raise ConfigEntryNotReady(f"Could not connect to Hcalory heater {address}")

    async def poll_status() -> None:
        """Poll status to keep the connection alive; reconnect if it drops."""
        loop = asyncio.get_running_loop()
        next_reconnect = 0.0
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            try:
                if client.is_connected:
                    await client.request_status()
                elif loop.time() >= next_reconnect:
                    _LOGGER.debug("Not connected, attempting reconnect")
                    if not await client.connect():
                        next_reconnect = loop.time() + RECONNECT_INTERVAL
            except Exception:  # keep polling whatever happens
                _LOGGER.exception("Error while polling heater")

    poll_task = entry.async_create_background_task(
        hass, poll_status(), f"{DOMAIN} poll {address}"
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "client": client,
        "poll_task": poll_task,
    }

    @callback
    def _async_update_ble(
        service_info: bluetooth.BluetoothServiceInfoBleak,
        change: bluetooth.BluetoothChange,
    ) -> None:
        """Keep the BLE device reference current from advertisements."""
        client.set_ble_device(service_info.device)

    entry.async_on_unload(
        bluetooth.async_register_callback(
            hass,
            _async_update_ble,
            BluetoothCallbackMatcher({ADDRESS: address}),
            bluetooth.BluetoothScanningMode.PASSIVE,
        )
    )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and release the heater's single connection."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        data = hass.data[DOMAIN].pop(entry.entry_id)

        # Stop polling first so it can't reconnect after we disconnect
        poll_task: asyncio.Task = data["poll_task"]
        poll_task.cancel()
        try:
            await poll_task
        except asyncio.CancelledError:
            pass

        client: HcaloryBleClient = data["client"]
        await client.disconnect()

    return unload_ok
