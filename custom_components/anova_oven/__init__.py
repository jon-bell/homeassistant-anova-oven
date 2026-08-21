"""Anova Oven integration — native port of homebridge-plugin-anova-toast."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError, ConfigEntryNotReady

from .api import AnovaAuthError, AnovaCloudHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SWITCH,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.CLIMATE,
    Platform.HUMIDIFIER,
    Platform.FAN,
]

type AnovaOvenConfigEntry = ConfigEntry[AnovaCloudHub]


async def async_setup_entry(hass: HomeAssistant, entry: AnovaOvenConfigEntry) -> bool:
    """Set up Anova Oven from a config entry."""
    hub = AnovaCloudHub(
        hass, entry, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )

    try:
        await hub.async_start()
    except AnovaAuthError as err:
        await hub.async_stop()
        raise ConfigEntryError("Anova cloud authentication failed") from err
    except Exception as err:  # noqa: BLE001
        # async_start() may have already handed the socket to a background
        # task (e.g. it timed out waiting for the first auth event) — stop it
        # rather than leaving an orphaned reconnect loop behind a failed entry.
        await hub.async_stop()
        raise ConfigEntryNotReady(f"Cannot reach Anova cloud: {err}") from err

    entry.runtime_data = hub
    entry.async_on_unload(hub.async_stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: AnovaOvenConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
