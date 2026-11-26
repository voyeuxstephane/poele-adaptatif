"""Boutons + / − (comme sur la carte du dashboard)."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controller import PoeleController
from .entity import PoeleEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c: PoeleController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            AdjustButton(c, "adjust_plus", "Plus", "mdi:plus", 1),
            AdjustButton(c, "adjust_minus", "Moins", "mdi:minus", -1),
            ResetLearningButton(c),
            BootstrapLearningButton(c),
        ]
    )


class AdjustButton(PoeleEntity, ButtonEntity):
    """En Confort : consigne du poêle ±1 °C. Sinon : puissance ±5 %."""

    def __init__(self, controller: PoeleController, key: str, name: str, icon: str, sens: int) -> None:
        super().__init__(controller, key)
        self._attr_name = name
        self._attr_icon = icon
        self._sens = sens

    async def async_press(self) -> None:
        await self.controller.async_adjust(self._sens)


class ResetLearningButton(PoeleEntity, ButtonEntity):
    """Repart des valeurs de départ (utile seulement après un changement du poêle ou de la maison)."""

    _attr_name = "Réinitialiser l'apprentissage"
    _attr_icon = "mdi:restore-alert"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "reset_learning")

    async def async_press(self) -> None:
        await self.controller.learning.async_reset()
        await self.controller.async_evaluate()


class BootstrapLearningButton(PoeleEntity, ButtonEntity):
    """Apprend sur les chauffes déjà enregistrées par Home Assistant (3 derniers jours)."""

    _attr_name = "Apprendre sur l'historique"
    _attr_icon = "mdi:history"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "bootstrap_learning")

    async def async_press(self) -> None:
        await self.controller.async_bootstrap()
