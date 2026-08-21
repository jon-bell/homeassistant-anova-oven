"""Config flow for Anova Oven integration."""

from __future__ import annotations

import json
import logging
from typing import Any, override

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import AnovaApiError, AnovaAuthError, async_fetch_id_token
from .const import CONF_RECIPES, DEFAULT_RECIPES, DOMAIN

_LOGGER = logging.getLogger(__name__)

USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


def _parse_and_validate_recipes(raw: str) -> list[dict[str, Any]]:
    """Parse the options-flow recipes textarea into the plugin's recipe shape.

    Raises ValueError with a short reason on anything malformed; callers map
    that to a form error rather than a traceback.
    """
    try:
        recipes = json.loads(raw)
    except json.JSONDecodeError as err:
        raise ValueError("invalid_json") from err
    if not isinstance(recipes, list) or not recipes:
        raise ValueError("not_a_list")
    for recipe in recipes:
        if not isinstance(recipe, dict):
            raise ValueError("not_a_list")
        if not isinstance(recipe.get("name"), str) or not recipe["name"]:
            raise ValueError("missing_name")
        stages = recipe.get("stages")
        if not isinstance(stages, list) or not stages:
            raise ValueError("missing_stages")
        for stage in stages:
            if not isinstance(stage, dict):
                raise ValueError("missing_stages")
            for required_key in (
                "temperatureBulbs",
                "heatingElements",
                "fan",
                "vent",
            ):
                if required_key not in stage:
                    raise ValueError(f"stage_missing_{required_key}")
    return recipes


async def _validate_credentials(hass, email: str, password: str) -> None:
    """Attempt a Firebase login; raises AnovaAuthError / AnovaApiError on failure."""
    await async_fetch_id_token(async_get_clientsession(hass), email, password)


class AnovaOvenConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Anova Oven."""

    VERSION = 1

    _reauth_entry: ConfigEntry | None = None

    @override
    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial user setup step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await _validate_credentials(
                    self.hass, user_input[CONF_EMAIL], user_input[CONF_PASSWORD]
                )
            except AnovaAuthError:
                errors["base"] = "invalid_auth"
            except AnovaApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating Anova credentials")
                errors["base"] = "unknown"

            if not errors:
                await self.async_set_unique_id(user_input[CONF_EMAIL].lower())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Anova Oven ({user_input[CONF_EMAIL]})",
                    data={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                    options={CONF_RECIPES: json.dumps(DEFAULT_RECIPES)},
                )

        return self.async_show_form(
            step_id="user", data_schema=USER_SCHEMA, errors=errors
        )

    @override
    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> ConfigFlowResult:
        """Handle re-authentication triggered by a websocket auth failure."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh password for an existing entry."""
        errors: dict[str, str] = {}
        assert self._reauth_entry is not None

        if user_input is not None:
            try:
                await _validate_credentials(
                    self.hass,
                    self._reauth_entry.data[CONF_EMAIL],
                    user_input[CONF_PASSWORD],
                )
            except AnovaAuthError:
                errors["base"] = "invalid_auth"
            except AnovaApiError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error validating Anova credentials")
                errors["base"] = "unknown"

            if not errors:
                self.hass.config_entries.async_update_entry(
                    self._reauth_entry,
                    data={
                        **self._reauth_entry.data,
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
                await self.hass.config_entries.async_reload(
                    self._reauth_entry.entry_id
                )
                return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"email": self._reauth_entry.data[CONF_EMAIL]},
        )

    @staticmethod
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return AnovaOvenOptionsFlow()


class AnovaOvenOptionsFlow(OptionsFlow):
    """Edit the favorite-recipe list (the switches other than Power)."""

    @override
    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show/validate the recipes-as-JSON textarea.

        Recipes are stage-graph JSON identical in shape to the plugin's
        config.json.example `recipes` array — there's no form UI for the
        stage graph, same as there wasn't one in Homebridge's config.json.
        """
        errors: dict[str, str] = {}
        current = self.config_entry.options.get(
            CONF_RECIPES, json.dumps(DEFAULT_RECIPES)
        )

        if user_input is not None:
            raw = user_input[CONF_RECIPES]
            try:
                _parse_and_validate_recipes(raw)
            except ValueError as err:
                errors["base"] = "invalid_recipes"
                _LOGGER.debug("Invalid recipes JSON: %s", err)
                current = raw
            else:
                return self.async_create_entry(data={CONF_RECIPES: raw})

        schema = vol.Schema(
            {
                vol.Required(CONF_RECIPES, default=current): TextSelector(
                    TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)
                )
            }
        )
        return self.async_show_form(
            step_id="init", data_schema=schema, errors=errors
        )
