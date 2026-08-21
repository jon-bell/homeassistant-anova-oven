"""Humidifier platform for Anova Oven — live steam/humidity control.

Maps nodes.steamGenerators. The oven's two steam modes don't both mean
"percent relative humidity" — `relative-humidity` does, `steam-percentage` is
a generator duty-cycle rate — but both are 0-100 setpoints and `humidifier`
is the only HA domain built around a 0-100 target, so both ride
target_humidity with `mode` distinguishing which one you're actually
setting. See manual_cook.py for how a live change gets applied while cooking.
"""

from __future__ import annotations

from homeassistant.components.humidifier import (
    HumidifierDeviceClass,
    HumidifierEntity,
    HumidifierEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaOvenConfigEntry
from .api import AnovaCloudHub, AnovaOven
from .entity import AnovaOvenEntity
from .util import get_path

MODE_RELATIVE_HUMIDITY = "relative_humidity"
MODE_STEAM_PERCENTAGE = "steam_percentage"

_MODE_TO_PROTOCOL = {
    MODE_RELATIVE_HUMIDITY: "relative-humidity",
    MODE_STEAM_PERCENTAGE: "steam-percentage",
}
_PROTOCOL_TO_MODE = {v: k for k, v in _MODE_TO_PROTOCOL.items()}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaOvenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up an Anova Oven humidifier entity for each oven as it's discovered."""
    hub = entry.runtime_data

    def _add_oven(oven: AnovaOven) -> None:
        async_add_entities([AnovaHumidifier(hub, oven)])

    entry.async_on_unload(hub.async_add_oven_listener(_add_oven))
    for oven in hub.ovens.values():
        _add_oven(oven)


class AnovaHumidifier(AnovaOvenEntity, HumidifierEntity):
    """Steam generator control: target humidity/steam-rate + mode."""

    _attr_device_class = HumidifierDeviceClass.HUMIDIFIER
    _attr_supported_features = HumidifierEntityFeature.MODES
    _attr_available_modes = [MODE_RELATIVE_HUMIDITY, MODE_STEAM_PERCENTAGE]
    _attr_min_humidity = 0
    _attr_max_humidity = 100
    _attr_icon = "mdi:kettle-steam"

    def __init__(self, hub: AnovaCloudHub, oven: AnovaOven) -> None:
        super().__init__(hub, oven, "steam")
        self._attr_name = "Steam"

    def _live_steam(self) -> dict:
        return get_path(self._oven.state, "nodes", "steamGenerators") or {}

    def _live_setpoint(self) -> float | None:
        steam = self._live_steam()
        key = "steamPercentage" if steam.get("mode") == "steam-percentage" else "relativeHumidity"
        return get_path(steam, key, "setpoint")

    @property
    def mode(self) -> str:
        protocol_mode = self._oven.pending.steam_mode or self._live_steam().get("mode")
        return _PROTOCOL_TO_MODE.get(protocol_mode, MODE_RELATIVE_HUMIDITY)

    @property
    def target_humidity(self) -> float | None:
        if self._oven.pending.humidity_percent is not None:
            return self._oven.pending.humidity_percent
        return self._live_setpoint()

    @property
    def current_humidity(self) -> float | None:
        # Only meaningful in relative-humidity mode; steam-percentage has no
        # comparable "current %" reading in the state payload.
        return get_path(self._oven.state, "nodes", "steamGenerators", "relativeHumidity", "current")

    @property
    def is_on(self) -> bool:
        return self._oven.is_on and bool(self.target_humidity)

    async def _stage_and_maybe_apply(self) -> None:
        if self._oven.is_on:
            await self._hub.async_apply_manual_stage(self._oven)
        else:
            self.async_write_ha_state()

    async def async_set_humidity(self, humidity: int) -> None:
        self._oven.pending.humidity_percent = humidity
        await self._stage_and_maybe_apply()

    async def async_set_mode(self, mode: str) -> None:
        self._oven.pending.steam_mode = _MODE_TO_PROTOCOL.get(mode, "relative-humidity")
        await self._stage_and_maybe_apply()

    async def async_turn_on(self, **kwargs) -> None:
        if self._oven.pending.humidity_percent is None and not self._live_setpoint():
            self._oven.pending.humidity_percent = 100
        await self._stage_and_maybe_apply()

    async def async_turn_off(self, **kwargs) -> None:
        self._oven.pending.humidity_percent = 0
        await self._stage_and_maybe_apply()
