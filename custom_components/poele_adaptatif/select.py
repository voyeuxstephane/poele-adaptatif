"""Mode du poêle et mode d'anticipation."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    ANTICIPATION_FIXED,
    ANTICIPATION_LEARNED,
    ANTICIPATION_OFF,
    DOMAIN,
    MODES,
    SET_ANTICIPATION_MODE,
)
from .controller import PoeleController
from .entity import PoeleEntity, ProxyEntity

ANTICIPATION_LABELS = {
    ANTICIPATION_OFF: "Désactivée",
    ANTICIPATION_FIXED: "Fixe",
    ANTICIPATION_LEARNED: "Apprise",
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c: PoeleController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ModeSelect(c), AnticipationSelect(c)])


class ModeSelect(ProxyEntity, SelectEntity):
    """Confort / Auto / Manuel (commande du poêle)."""

    _attr_name = "Mode"
    _attr_icon = "mdi:fire-circle"
    _attr_options = MODES

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "mode", controller.climate)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Le mode Auto / Manuel dépend aussi de l'interrupteur des plages Rika
        self.async_on_remove(
            async_track_state_change_event(
                self.hass, [self.controller.heating_times], self._source_changed
            )
        )

    @property
    def current_option(self) -> str | None:
        return self.controller.mode

    async def async_select_option(self, option: str) -> None:
        await self.controller.async_set_mode(option)


class AnticipationSelect(PoeleEntity, SelectEntity):
    """Désactivée : début de plage. Fixe : avance constante. Apprise : durée estimée par le modèle."""

    _attr_name = "Anticipation"
    _attr_icon = "mdi:clock-fast"
    _attr_options = list(ANTICIPATION_LABELS.values())

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "anticipation_mode")

    @property
    def current_option(self) -> str:
        return ANTICIPATION_LABELS.get(
            self.controller.settings[SET_ANTICIPATION_MODE], "Désactivée"
        )

    async def async_select_option(self, option: str) -> None:
        for key, label in ANTICIPATION_LABELS.items():
            if label == option:
                await self.controller.async_set_setting(SET_ANTICIPATION_MODE, key)
                return
