"""Switch platform for Hcalory HBU1S: the heater's auto start/stop setting."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN
from .client import HcaloryBleClient


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the auto start/stop switch."""
    client: HcaloryBleClient = hass.data[DOMAIN][entry.entry_id]["client"]
    async_add_entities([HcaloryAutoStartStopSwitch(entry, client)])


class HcaloryAutoStartStopSwitch(SwitchEntity, RestoreEntity):
    """The auto start/stop setting the heater is kept at.

    With auto start/stop on, the heater in temperature mode stops by itself
    when the room is warm enough and starts again by itself when it cools,
    even while it looks off. This switch holds the wanted setting (off unless
    turned on, remembered across restarts) and the integration keeps the
    heater matching it, undoing changes made at the heater's panel or in the
    app. Turning it on reaches the heater only while it is running. The
    heater's own reading is the climate entity's auto_start_stop attribute.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "auto_start_stop"
    _attr_icon = "mdi:thermostat-auto"

    def __init__(self, entry: ConfigEntry, client: HcaloryBleClient) -> None:
        """Initialize the switch."""
        self._client = client
        self._attr_unique_id = f"{entry.entry_id}_auto_start_stop"
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, entry.entry_id)})
        self._attr_is_on = False

    async def async_added_to_hass(self) -> None:
        """Restore the wanted setting; the status poll then applies it."""
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._attr_is_on = last is not None and last.state == STATE_ON
        self._client.set_wanted_auto_start_stop(self._attr_is_on)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Keep the heater's auto start/stop on."""
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Keep the heater's auto start/stop off."""
        await self._set(False)

    async def _set(self, wanted: bool) -> None:
        self._attr_is_on = wanted
        self._client.set_wanted_auto_start_stop(wanted)
        self.async_write_ha_state()
        await self._client.sync_auto_start_stop()
