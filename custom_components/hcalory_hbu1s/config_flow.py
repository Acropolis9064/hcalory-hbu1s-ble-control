"""Config flow for Hcalory HBU1S integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_ADDRESS
from homeassistant.data_entry_flow import FlowResult

from .const import DOMAIN, SERVICE_UUID

_LOGGER = logging.getLogger(__name__)


class HcaloryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Hcalory HBU1S."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._discovered_devices: dict[str, BluetoothServiceInfoBleak] = {}

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the Bluetooth discovery step."""
        await self.async_set_unique_id(discovery_info.address)
        self._abort_if_unique_id_configured()
        
        self._discovery_info = discovery_info
        
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm discovery."""
        assert self._discovery_info is not None
        
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovery_info.name or "Hcalory Heater",
                data={
                    CONF_ADDRESS: self._discovery_info.address,
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._discovery_info.name or self._discovery_info.address
            },
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the user step to pick discovered device."""
        if user_input is not None:
            address = user_input[CONF_ADDRESS]
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()
            
            discovery_info = self._discovered_devices[address]
            
            return self.async_create_entry(
                title=discovery_info.name or "Hcalory Heater",
                data={
                    CONF_ADDRESS: address,
                },
            )

        # Find all Hcalory heaters
        for info in async_discovered_service_info(self.hass, connectable=True):
            if SERVICE_UUID.lower() in [s.lower() for s in info.service_uuids]:
                self._discovered_devices[info.address] = info
            elif info.name and info.name.startswith("Heater"):
                self._discovered_devices[info.address] = info

        if not self._discovered_devices:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema={
                CONF_ADDRESS: list(self._discovered_devices.keys())
            },
        )
