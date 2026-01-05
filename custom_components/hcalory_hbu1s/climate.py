"""Climate platform for Hcalory HBU1S."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MIN_TEMP, MAX_TEMP
from .client import HcaloryBleClient, HeaterStatus

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Hcalory climate entity."""
    client: HcaloryBleClient = hass.data[DOMAIN][entry.entry_id]["client"]
    
    async_add_entities([HcaloryClimate(entry, client)])


class HcaloryClimate(ClimateEntity):
    """Representation of a Hcalory heater."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_min_temp = MIN_TEMP
    _attr_max_temp = MAX_TEMP
    _attr_target_temperature_step = 1

    def __init__(
        self,
        entry: ConfigEntry,
        client: HcaloryBleClient,
    ) -> None:
        """Initialize the climate entity."""
        self._entry = entry
        self._client = client
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Hcalory",
            model="HBU1S 5KW",
        )
        
        # Set initial callback
        self._client._status_callback = self._on_status_update

    @callback
    def _on_status_update(self, status: HeaterStatus) -> None:
        """Handle status updates from the heater."""
        self.async_write_ha_state()

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self._client.is_connected

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        if self._client.status.is_on:
            return HVACMode.HEAT
        return HVACMode.OFF

    @property
    def current_temperature(self) -> float | None:
        """Return the current ambient temperature."""
        temp = self._client.status.ambient_temp
        return temp if temp > 0 else None

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature."""
        return self._client.status.target_temp

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        return {
            "state": self._client.status.state_string,
            "body_temperature": self._client.status.body_temp,
            "connected": self._client.status.connected,
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        _LOGGER.info("Setting HVAC mode to: %s", hvac_mode)
        if hvac_mode == HVACMode.HEAT:
            await self._client.turn_on()
        elif hvac_mode == HVACMode.OFF:
            await self._client.turn_off()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature."""
        if (temp := kwargs.get(ATTR_TEMPERATURE)) is not None:
            _LOGGER.info("Setting temperature to: %s", temp)
            await self._client.set_temperature(int(temp))

    async def async_turn_on(self) -> None:
        """Turn on the heater."""
        _LOGGER.info("Turn ON called")
        await self._client.turn_on()

    async def async_turn_off(self) -> None:
        """Turn off the heater."""
        _LOGGER.info("Turn OFF called")
        await self._client.turn_off()
