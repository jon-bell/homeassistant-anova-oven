"""Base entity for Anova Oven integration."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity

from .api import AnovaCloudHub, AnovaOven
from .const import DOMAIN, SIGNAL_OVEN_UPDATE


class AnovaOvenEntity(Entity):
    """Base class for all entities tied to a single Anova oven."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(
        self, hub: AnovaCloudHub, oven: AnovaOven, unique_id_suffix: str
    ) -> None:
        """Initialize."""
        self._hub = hub
        self._oven = oven
        self._attr_unique_id = f"{oven.cooker_id}_{unique_id_suffix}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, oven.cooker_id)},
            manufacturer="Anova Culinary",
            model="Precision Oven",
            name=oven.name,
            serial_number=oven.cooker_id,
            sw_version=oven.system_info.get("firmwareVersion"),
            hw_version=oven.system_info.get("hardwareVersion"),
        )

    @property
    def available(self) -> bool:
        """Entities need a live websocket and at least one state push."""
        return self._hub.connected and self._oven.state is not None

    async def async_added_to_hass(self) -> None:
        """Subscribe to state pushes for this oven."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                f"{SIGNAL_OVEN_UPDATE}_{self._oven.cooker_id}",
                self._handle_oven_update,
            )
        )

    @callback
    def _handle_oven_update(self) -> None:
        self.async_write_ha_state()
