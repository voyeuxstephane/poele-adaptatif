"""Plage de chauffe active."""
from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controller import PoeleController
from .entity import PoeleEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([ActiveWindowSensor(hass.data[DOMAIN][entry.entry_id])])


class ActiveWindowSensor(PoeleEntity, BinarySensorEntity):
    """Allumé quand une plage du calendrier est en cours."""

    _attr_name = "Plage active"
    _attr_icon = "mdi:calendar-check"

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "window_active")

    @property
    def is_on(self) -> bool:
        return self.controller.decision.in_window
