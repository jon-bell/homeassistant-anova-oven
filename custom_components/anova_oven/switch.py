"""Switch platform for Anova Oven — power + one switch per favorite recipe.

Port of platformAccessory.ts's per-recipe HomeKit switches. Turning a recipe
switch on starts that recipe's stage sequence; off always stops the cook
(matching the plugin, which doesn't check the off switch belongs to the
currently-running recipe). The "Power" switch reflects whether *any* cook is
active and starts the plugin's POWER_ON_STAGES sequence, mirroring the primary
service in the original accessory.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaOvenConfigEntry
from .api import AnovaCloudHub, AnovaOven
from .const import POWER_ON_STAGES
from .entity import AnovaOvenEntity
from .recipes import load_recipes

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaOvenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Anova Oven switches for each oven as it's discovered."""
    hub = entry.runtime_data
    recipes = load_recipes(entry)

    def _add_oven(oven: AnovaOven) -> None:
        entities: list[SwitchEntity] = [AnovaPowerSwitch(hub, oven)]
        entities.extend(
            AnovaRecipeSwitch(hub, oven, recipe["name"], recipe["stages"])
            for recipe in recipes
        )
        async_add_entities(entities)

    entry.async_on_unload(hub.async_add_oven_listener(_add_oven))
    for oven in hub.ovens.values():
        _add_oven(oven)


class AnovaPowerSwitch(AnovaOvenEntity, SwitchEntity):
    """On while any cook is active; on-set starts the plugin's power-on stages."""

    _attr_icon = "mdi:toaster-oven"

    def __init__(self, hub: AnovaCloudHub, oven: AnovaOven) -> None:
        super().__init__(hub, oven, "power")
        self._attr_name = "Power"

    @property
    def is_on(self) -> bool:
        return self._oven.is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._hub.async_start_cook(self._oven, POWER_ON_STAGES)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_stop_cook(self._oven)


class AnovaRecipeSwitch(AnovaOvenEntity, SwitchEntity):
    """On while this exact recipe's stages are the active cook."""

    _attr_icon = "mdi:chef-hat"

    def __init__(
        self,
        hub: AnovaCloudHub,
        oven: AnovaOven,
        name: str,
        stages: list[dict[str, Any]],
    ) -> None:
        # Recipe names come from user-editable options, not a fixed enum, so a
        # slug of the name is the most stable unique_id component available.
        slug = name.lower().replace(" ", "_")
        super().__init__(hub, oven, f"recipe_{slug}")
        self._attr_name = name
        self._stages = stages

    @property
    def is_on(self) -> bool:
        return self._oven.is_cooking_stages(self._stages)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._hub.async_start_cook(self._oven, self._stages)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._hub.async_stop_cook(self._oven)
