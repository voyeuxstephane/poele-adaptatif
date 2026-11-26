"""Pilotage automatique et interrupteurs du poêle."""
from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SET_PILOTAGE
from .controller import PoeleController
from .entity import PoeleEntity, ProxyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c: PoeleController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            PilotageSwitch(c),
            ProxySwitch(c, "stove_on_off", "Marche / arrêt", c.on_off, "mdi:power"),
            ProxySwitch(c, "rika_heating_times", "Plages horaires Rika", c.heating_times, "mdi:calendar-clock"),
        ]
    )


class PilotageSwitch(PoeleEntity, SwitchEntity):
    """Interrupteur général : tant qu'il est coupé, aucune commande automatique n'est envoyée."""

    _attr_name = "Pilotage automatique"
    _attr_icon = "mdi:robot"

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "pilotage")

    @property
    def is_on(self) -> bool:
        return bool(self.controller.settings[SET_PILOTAGE])

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.controller.async_set_setting(SET_PILOTAGE, True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.controller.async_set_setting(SET_PILOTAGE, False)


class ProxySwitch(ProxyEntity, SwitchEntity):
    """Reflète un interrupteur du poêle et lui transmet les commandes."""

    def __init__(self, controller, key, name, source, icon) -> None:
        super().__init__(controller, key, source)
        self._attr_name = name
        self._attr_icon = icon

    @property
    def is_on(self) -> bool | None:
        state = self.source_state
        return None if state is None else state.state == STATE_ON

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self.hass.services.async_call(
            "switch", "turn_on", {"entity_id": self._source}, blocking=True
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.hass.services.async_call(
            "switch", "turn_off", {"entity_id": self._source}, blocking=True
        )
