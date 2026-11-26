"""Entités de base de l'intégration."""
from __future__ import annotations

from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.core import Event, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN
from .controller import PoeleController


class PoeleEntity(Entity):
    """Entité rattachée à l'appareil « Poêle adaptatif »."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, controller: PoeleController, key: str) -> None:
        self.controller = controller
        self._attr_unique_id = f"{controller.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, controller.entry.entry_id)},
            name="Poêle adaptatif",
            manufacturer="Personnel",
            model="Régulation du poêle Rika Firenet",
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self.controller.async_add_listener(self.async_write_ha_state))


class ProxyEntity(PoeleEntity):
    """Entité qui reflète une entité du poêle et lui transmet les commandes."""

    def __init__(self, controller: PoeleController, key: str, source: str) -> None:
        super().__init__(controller, key)
        self._source = source

    @property
    def source_state(self):
        return self.hass.states.get(self._source)

    @property
    def available(self) -> bool:
        state = self.source_state
        return state is not None and state.state != STATE_UNAVAILABLE

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(self.hass, [self._source], self._source_changed)
        )

    @callback
    def _source_changed(self, event: Event) -> None:
        self.async_write_ha_state()
