"""Climate platform for Hcalory HBU1S."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.climate import (
    ATTR_HVAC_MODE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MIN_TEMP, MAX_TEMP, MODE_GEAR, MODE_TEMPERATURE, HeaterState
from .client import HcaloryBleClient, HeaterStatus

PRESET_TEMPERATURE = "temperature"
PRESET_GEAR = "gear"
MODE_NAMES = {MODE_TEMPERATURE: PRESET_TEMPERATURE, MODE_GEAR: PRESET_GEAR}

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
    _attr_translation_key = "heater"
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_preset_modes = [PRESET_TEMPERATURE, PRESET_GEAR]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
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
    def hvac_action(self) -> HVACAction:
        """Return what the heater is doing right now."""
        state = self._client.status.state
        if state in (HeaterState.STARTING, HeaterState.RUNNING):
            return HVACAction.HEATING
        if state == HeaterState.COOLING_DOWN:
            return HVACAction.FAN
        return HVACAction.OFF

    @property
    def preset_mode(self) -> str | None:
        """Return the heater mode: temperature (thermostat) or gear (fixed level).

        While off this is the mode it was last running in, which is the mode
        it will resume in if simply powered on.
        """
        status = self._client.status
        mode = status.mode if status.is_on else status.last_mode
        return MODE_NAMES.get(mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Turn the heater on in the chosen mode."""
        _LOGGER.info("Setting preset mode to: %s", preset_mode)
        if preset_mode == PRESET_GEAR:
            await self._client.turn_on_gear()
        else:
            await self._client.turn_on()
        self.async_write_ha_state()

    @property
    def current_temperature(self) -> float | None:
        """Return the ambient temperature reported by the heater, in °C."""
        return self._client.status.ambient_temp

    @property
    def target_temperature(self) -> float | None:
        """Return the target temperature in °C."""
        return self._client.status.target_temp

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra state attributes."""
        status = self._client.status
        return {
            "state": status.state,
            "mode": MODE_NAMES.get(status.mode) if status.mode is not None else None,
            "gear_level": status.gear_level,
            "body_temperature": status.body_temp,
            "supply_voltage": status.voltage,
            "auto_start_stop": status.auto_start_stop,
            "display_units": "°F" if status.fahrenheit else "°C",
            "connected": status.connected,
        }

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode."""
        _LOGGER.info("Setting HVAC mode to: %s", hvac_mode)
        if hvac_mode == HVACMode.HEAT:
            await self._client.turn_on()
        elif hvac_mode == HVACMode.OFF:
            await self._client.turn_off()

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set target temperature, optionally with an HVAC mode in the same call.

        Voice assistants and HomeKit often send "heat to 18°C" as one call,
        so a HEAT mode here turns the heater on straight at that target.
        """
        temp = kwargs.get(ATTR_TEMPERATURE)
        target = round(temp) if temp is not None else None
        hvac_mode = kwargs.get(ATTR_HVAC_MODE)
        _LOGGER.info("Set temperature called: %s (hvac_mode %s)", target, hvac_mode)
        if hvac_mode == HVACMode.OFF:
            await self._client.turn_off()
        elif hvac_mode == HVACMode.HEAT:
            await self._client.turn_on(target)
        elif target is not None:
            await self._client.set_temperature(target)
        self.async_write_ha_state()

    async def async_turn_on(self) -> None:
        """Turn on the heater."""
        _LOGGER.info("Turn ON called")
        await self._client.turn_on()

    async def async_turn_off(self) -> None:
        """Turn off the heater."""
        _LOGGER.info("Turn OFF called")
        await self._client.turn_off()
