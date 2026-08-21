"""Fan platform for Anova Oven — replaces the old fan-speed sensor with a
live, adjustable control over nodes.fan.speed."""

from __future__ import annotations

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaOvenConfigEntry
from .api import AnovaCloudHub, AnovaOven
from .entity import AnovaOvenEntity
from .util import get_path


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaOvenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up an Anova Oven fan entity for each oven as it's discovered."""
    hub = entry.runtime_data

    def _add_oven(oven: AnovaOven) -> None:
        async_add_entities([AnovaFan(hub, oven)])

    entry.async_on_unload(hub.async_add_oven_listener(_add_oven))
    for oven in hub.ovens.values():
        _add_oven(oven)


class AnovaFan(AnovaOvenEntity, FanEntity):
    """Convection fan speed, 0-100%. See manual_cook.py for how a live
    change gets applied while cooking."""

    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    _attr_icon = "mdi:fan"

    def __init__(self, hub: AnovaCloudHub, oven: AnovaOven) -> None:
        super().__init__(hub, oven, "fan")
        self._attr_name = "Fan"

    @property
    def percentage(self) -> int | None:
        if self._oven.pending.fan_speed is not None:
            return self._oven.pending.fan_speed
        return get_path(self._oven.state, "nodes", "fan", "speed")

    @property
    def is_on(self) -> bool:
        return bool(self.percentage)

    async def async_set_percentage(self, percentage: int) -> None:
        self._oven.pending.fan_speed = percentage
        if self._oven.is_on:
            await self._hub.async_apply_manual_stage(self._oven)
        else:
            self.async_write_ha_state()

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs,
    ) -> None:
        await self.async_set_percentage(percentage if percentage is not None else 100)

    async def async_turn_off(self, **kwargs) -> None:
        await self.async_set_percentage(0)
