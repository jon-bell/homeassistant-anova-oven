"""Sensor platform for Anova Oven — telemetry from EVENT_APO_STATE.

Only fields the AnovaTypes.d.ts in the plugin actually documents are read;
everything else goes through .get() chains that degrade to `unknown` rather
than raising, since the cloud API is undocumented upstream (this is a
reverse-engineered protocol — see the plugin's README) and other oven
firmware/protocol versions may omit fields.
"""

from __future__ import annotations

import logging

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaOvenConfigEntry
from .api import AnovaCloudHub, AnovaOven
from .entity import AnovaOvenEntity
from .util import get_path as _get

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaOvenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Anova Oven sensors for each oven as it's discovered."""
    hub = entry.runtime_data

    def _add_oven(oven: AnovaOven) -> None:
        async_add_entities(
            [
                AnovaModeSensor(hub, oven),
                AnovaTemperatureSensor(hub, oven),
                AnovaTargetTemperatureSensor(hub, oven),
                AnovaTimerRemainingSensor(hub, oven),
                AnovaFirmwareVersionSensor(hub, oven),
            ]
        )

    entry.async_on_unload(hub.async_add_oven_listener(_add_oven))
    for oven in hub.ovens.values():
        _add_oven(oven)


class AnovaModeSensor(AnovaOvenEntity, SensorEntity):
    """idle / cook, straight from state.mode."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["idle", "cook"]
    _attr_icon = "mdi:stove"

    def __init__(self, hub: AnovaCloudHub, oven: AnovaOven) -> None:
        super().__init__(hub, oven, "mode")
        self._attr_name = "Mode"

    @property
    def native_value(self) -> str | None:
        return self._oven.mode


class AnovaTemperatureSensor(AnovaOvenEntity, SensorEntity):
    """Current cavity temperature, dry- or wet-bulb depending on active mode."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, hub: AnovaCloudHub, oven: AnovaOven) -> None:
        super().__init__(hub, oven, "temperature")
        self._attr_name = "Temperature"

    @property
    def native_value(self) -> float | None:
        bulbs = _get(self._oven.state, "nodes", "temperatureBulbs")
        mode = _get(bulbs, "mode")
        if mode not in ("dry", "wet"):
            return None
        return _get(bulbs, mode, "current", "celsius")


class AnovaTargetTemperatureSensor(AnovaOvenEntity, SensorEntity):
    """Active setpoint. Only documented for dry mode; wet-mode setpoint is read
    defensively (`.get()` chain) since the plugin's own type definitions don't
    confirm the field exists on that branch — see AnovaTypes.d.ts's duplicate
    `WetStatus` declaration."""

    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: AnovaCloudHub, oven: AnovaOven) -> None:
        super().__init__(hub, oven, "target_temperature")
        self._attr_name = "Target Temperature"

    @property
    def native_value(self) -> float | None:
        bulbs = _get(self._oven.state, "nodes", "temperatureBulbs")
        mode = _get(bulbs, "mode")
        if mode not in ("dry", "wet"):
            return None
        return _get(bulbs, mode, "setpoint", "celsius")


class AnovaTimerRemainingSensor(AnovaOvenEntity, SensorEntity):
    """Seconds left on the current stage's timer; unknown while idle."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.SECONDS
    _attr_icon = "mdi:timer-outline"

    def __init__(self, hub: AnovaCloudHub, oven: AnovaOven) -> None:
        super().__init__(hub, oven, "timer_remaining")
        self._attr_name = "Timer Remaining"

    @property
    def native_value(self) -> int | None:
        if self._oven.mode != "cook":
            return None
        return _get(self._oven.state, "nodes", "timer", "current")


class AnovaFirmwareVersionSensor(AnovaOvenEntity, SensorEntity):
    """Diagnostic mirror of the device_info sw_version, as its own history."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:chip"

    def __init__(self, hub: AnovaCloudHub, oven: AnovaOven) -> None:
        super().__init__(hub, oven, "firmware_version")
        self._attr_name = "Firmware Version"

    @property
    def native_value(self) -> str | None:
        return self._oven.system_info.get("firmwareVersion")
