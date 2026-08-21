"""Climate platform for Anova Oven — live temperature control + recipe presets.

hvac_mode OFF/HEAT maps to CMD_APO_STOP / CMD_APO_START; presets are the same
named recipes as the switch.py switches (selecting one starts that exact
stage list, same as flipping its switch). Dragging target_temperature while
a cook is active re-issues CMD_APO_START with just the setpoint changed — see
manual_cook.py's module docstring for why that's the only way to do a live
adjustment, and for the shared `oven.pending` staging area this shares with
humidifier.py/fan.py.
"""

from __future__ import annotations

import logging

from homeassistant.components.climate import (
    PRESET_NONE,
    ClimateEntity,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaOvenConfigEntry
from .api import AnovaCloudHub, AnovaOven
from .entity import AnovaOvenEntity
from .recipes import load_recipes
from .util import get_path

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaOvenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up an Anova Oven climate entity for each oven as it's discovered."""
    hub = entry.runtime_data
    recipes = load_recipes(entry)

    def _add_oven(oven: AnovaOven) -> None:
        async_add_entities([AnovaClimate(hub, oven, recipes)])

    entry.async_on_unload(hub.async_add_oven_listener(_add_oven))
    for oven in hub.ovens.values():
        _add_oven(oven)


class AnovaClimate(AnovaOvenEntity, ClimateEntity):
    """The oven itself: temperature setpoint, on/off, and recipe presets."""

    # No suffix — this is the device's primary entity (has_entity_name + name
    # None means the entity is named after the device, e.g. just "Countertop
    # Oven" rather than "Countertop Oven Climate").
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_target_temperature_step = 1
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.HEAT]
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.PRESET_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    # Both hvac_modes are unambiguous here (only OFF and HEAT exist), but
    # explicit async_turn_on/off below avoid relying on ClimateEntity's
    # implicit TURN_ON/OFF fallback behavior — same reasoning as
    # mitsubishi_comfort's climate.py in this repo.
    _enable_turn_on_off_backwards_compatibility = False
    # Covers the recipe range (25C cooldown floor .. 250C toast) with margin;
    # the oven itself is the actual limiter, this just keeps the slider sane.
    _attr_min_temp = 25
    _attr_max_temp = 260

    def __init__(
        self, hub: AnovaCloudHub, oven: AnovaOven, recipes: list[dict]
    ) -> None:
        super().__init__(hub, oven, "climate")
        self._recipes = {recipe["name"]: recipe for recipe in recipes}
        self._attr_preset_modes = [PRESET_NONE, *self._recipes.keys()]

    def _bulb_mode(self) -> str | None:
        return get_path(self._oven.state, "nodes", "temperatureBulbs", "mode")

    @property
    def hvac_mode(self) -> HVACMode:
        return HVACMode.HEAT if self._oven.is_on else HVACMode.OFF

    @property
    def hvac_action(self) -> HVACAction | None:
        if self._oven.state is None:
            return None
        return HVACAction.HEATING if self._oven.is_on else HVACAction.OFF

    @property
    def current_temperature(self) -> float | None:
        mode = self._bulb_mode()
        if mode not in ("dry", "wet"):
            return None
        return get_path(self._oven.state, "nodes", "temperatureBulbs", mode, "current", "celsius")

    @property
    def target_temperature(self) -> float | None:
        if self._oven.pending.temperature_celsius is not None:
            return self._oven.pending.temperature_celsius
        mode = self._bulb_mode()
        if mode not in ("dry", "wet"):
            return None
        return get_path(self._oven.state, "nodes", "temperatureBulbs", mode, "setpoint", "celsius")

    @property
    def preset_mode(self) -> str:
        if not self._oven.is_on:
            return PRESET_NONE
        for name, recipe in self._recipes.items():
            if self._oven.is_cooking_stages(recipe["stages"]):
                return name
        return PRESET_NONE  # cooking, but not a recognized recipe (manual/staged)

    async def async_set_temperature(self, **kwargs) -> None:
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._oven.pending.temperature_celsius = temperature
        if self._oven.is_on:
            await self._hub.async_apply_manual_stage(self._oven)
        else:
            self.async_write_ha_state()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        if hvac_mode == HVACMode.OFF:
            await self._hub.async_stop_cook(self._oven)
        elif hvac_mode == HVACMode.HEAT and not self._oven.is_on:
            await self._hub.async_apply_manual_stage(self._oven)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        if preset_mode == PRESET_NONE:
            return
        recipe = self._recipes.get(preset_mode)
        if recipe is None:
            raise ServiceValidationError(f"Unknown recipe preset: {preset_mode}")
        await self._hub.async_start_cook(self._oven, recipe["stages"])

    async def async_turn_on(self) -> None:
        await self.async_set_hvac_mode(HVACMode.HEAT)

    async def async_turn_off(self) -> None:
        await self.async_set_hvac_mode(HVACMode.OFF)
