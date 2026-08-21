"""Shared recipe-list loading for switch.py and climate.py."""

from __future__ import annotations

import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry

from .const import CONF_RECIPES, DEFAULT_RECIPES

_LOGGER = logging.getLogger(__name__)


def load_recipes(entry: ConfigEntry) -> list[dict[str, Any]]:
    """Parse the entry's stored recipes JSON, falling back to the defaults."""
    try:
        recipes = json.loads(entry.options.get(CONF_RECIPES, "")) or DEFAULT_RECIPES
    except json.JSONDecodeError:
        _LOGGER.warning("Stored recipes JSON is invalid, falling back to defaults")
        recipes = DEFAULT_RECIPES
    return recipes
