"""Configuration de l'intégration (choix des entités du poêle)."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CLIMATE,
    CONF_DIAG,
    CONF_FAN,
    CONF_HEATING_TIMES,
    CONF_MAIN_STATE,
    CONF_ON_OFF,
    CONF_OUTDOOR_TEMP,
    CONF_PELLETS,
    CONF_POWER,
    CONF_ROOM_TEMP,
    CONF_STATUS,
    DEFAULT_ENTITIES,
    DOMAIN,
)


def _entity(domain: str | list[str]) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=domain))


def _schema(defaults: dict[str, str]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_CLIMATE, default=defaults[CONF_CLIMATE]): _entity("climate"),
            vol.Required(CONF_ON_OFF, default=defaults[CONF_ON_OFF]): _entity("switch"),
            vol.Required(CONF_HEATING_TIMES, default=defaults[CONF_HEATING_TIMES]): _entity("switch"),
            vol.Required(CONF_POWER, default=defaults[CONF_POWER]): _entity("number"),
            vol.Required(CONF_STATUS, default=defaults[CONF_STATUS]): _entity("sensor"),
            vol.Required(CONF_MAIN_STATE, default=defaults[CONF_MAIN_STATE]): _entity("sensor"),
            vol.Required(CONF_PELLETS, default=defaults[CONF_PELLETS]): _entity("sensor"),
            vol.Required(CONF_ROOM_TEMP, default=defaults[CONF_ROOM_TEMP]): _entity("sensor"),
            vol.Required(CONF_OUTDOOR_TEMP, default=defaults[CONF_OUTDOOR_TEMP]): _entity("sensor"),
            vol.Required(CONF_FAN, default=defaults[CONF_FAN]): _entity("sensor"),
            vol.Required(CONF_DIAG, default=defaults[CONF_DIAG]): _entity("sensor"),
        }
    )


class PoeleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Création de l'unique entrée de l'intégration."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(title="Poêle adaptatif", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema(DEFAULT_ENTITIES))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> "PoeleOptionsFlow":
        return PoeleOptionsFlow()


class PoeleOptionsFlow(OptionsFlow):
    """Modification des entités utilisées (rechargement automatique)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = {**DEFAULT_ENTITIES, **self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(current))
