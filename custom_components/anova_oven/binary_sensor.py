"""Binary sensor platform for Anova Oven — door, water tank, connectivity, faults."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import AnovaOvenConfigEntry
from .api import AnovaCloudHub, AnovaOven
from .entity import AnovaOvenEntity
from .util import get_path as _get


async def async_setup_entry(
    hass: HomeAssistant,
    entry: AnovaOvenConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Anova Oven binary sensors for each oven as it's discovered."""
    hub = entry.runtime_data

    def _add_oven(oven: AnovaOven) -> None:
        async_add_entities(
            [
                AnovaDoorSensor(hub, oven),
                AnovaWaterTankSensor(hub, oven),
                AnovaConnectivitySensor(hub, oven),
                AnovaProblemSensor(hub, oven),
            ]
        )

    entry.async_on_unload(hub.async_add_oven_listener(_add_oven))
    for oven in hub.ovens.values():
        _add_oven(oven)


class AnovaDoorSensor(AnovaOvenEntity, BinarySensorEntity):
    """On (open) when nodes.door.closed is false."""

    _attr_device_class = BinarySensorDeviceClass.DOOR

    def __init__(self, hub: AnovaCloudHub, oven: AnovaOven) -> None:
        super().__init__(hub, oven, "door")
        self._attr_name = "Door"

    @property
    def is_on(self) -> bool | None:
        closed = _get(self._oven.state, "nodes", "door", "closed")
        return None if closed is None else not closed


class AnovaWaterTankSensor(AnovaOvenEntity, BinarySensorEntity):
    """Problem sensor: on when the water tank needs a refill."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:water-alert"

    def __init__(self, hub: AnovaCloudHub, oven: AnovaOven) -> None:
        super().__init__(hub, oven, "water_tank_empty")
        self._attr_name = "Water Tank Empty"

    @property
    def is_on(self) -> bool | None:
        return _get(self._oven.state, "nodes", "waterTank", "empty")


class AnovaConnectivitySensor(AnovaOvenEntity, BinarySensorEntity):
    """On when the oven itself reports online (systemInfo.online).

    Distinct from entity `available`, which tracks whether *our* websocket to
    the Anova cloud is up. A cloud outage makes every entity unavailable; the
    oven merely losing its own Wi-Fi shows up here instead, same distinction
    the plugin's SystemInfo.online field exists to make.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: AnovaCloudHub, oven: AnovaOven) -> None:
        super().__init__(hub, oven, "online")
        self._attr_name = "Online"

    @property
    def is_on(self) -> bool:
        return self._oven.online


class AnovaProblemSensor(AnovaOvenEntity, BinarySensorEntity):
    """Aggregate fault flag: any triac, heating element, fan, evaporator, or
    boiler reporting `failed`/`overheated`/`descaleRequired`, or the UI
    circuit reporting a communication failure."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, hub: AnovaCloudHub, oven: AnovaOven) -> None:
        super().__init__(hub, oven, "problem")
        self._attr_name = "Problem"

    @property
    def is_on(self) -> bool | None:
        state = self._oven.state
        if state is None:
            return None
        nodes = state.get("nodes", {})
        flags = [
            _get(state, "systemInfo", "triacsFailed"),
            _get(nodes, "heatingElements", "top", "failed"),
            _get(nodes, "heatingElements", "bottom", "failed"),
            _get(nodes, "heatingElements", "rear", "failed"),
            _get(nodes, "fan", "failed"),
            _get(nodes, "steamGenerators", "evaporator", "failed"),
            _get(nodes, "steamGenerators", "evaporator", "overheated"),
            _get(nodes, "steamGenerators", "boiler", "failed"),
            _get(nodes, "steamGenerators", "boiler", "overheated"),
            _get(nodes, "steamGenerators", "boiler", "descaleRequired"),
            _get(nodes, "temperatureBulbs", "dryTop", "overheated"),
            _get(nodes, "temperatureBulbs", "dryBottom", "overheated"),
            _get(nodes, "temperatureBulbs", "wet", "doseFailed"),
            _get(nodes, "userInterfaceCircuit", "communicationFailed"),
            _get(nodes, "lamp", "failed"),
        ]
        return any(bool(flag) for flag in flags)
