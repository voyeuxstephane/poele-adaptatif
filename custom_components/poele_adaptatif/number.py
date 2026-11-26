"""Réglages numériques et commandes de puissance / consigne du poêle."""
from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNKNOWN, EntityCategory, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import (
    CLIMATE_MAX,
    CLIMATE_MIN,
    DOMAIN,
    POWER_MAX,
    POWER_MIN,
    POWER_STEP,
    SET_ADVANCE_MAX,
    SET_ANTICIPATION_MIN,
    SET_COOLDOWN,
    SET_CONSIGNE,
    SET_HYSTERESIS,
    SET_MIN_RUN,
    SET_POWER_PLAN,
)
from .controller import PoeleController
from .entity import PoeleEntity, ProxyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c: PoeleController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            SettingNumber(c, SET_CONSIGNE, "Consigne", 14, 28, 0.5, UnitOfTemperature.CELSIUS, "mdi:thermometer-check", NumberDeviceClass.TEMPERATURE, False),
            SettingNumber(c, SET_HYSTERESIS, "Hystérésis", 0.1, 2, 0.1, UnitOfTemperature.CELSIUS, "mdi:swap-vertical", None, True),
            SettingNumber(c, SET_ANTICIPATION_MIN, "Avance d'allumage", 0, 240, 5, UnitOfTime.MINUTES, "mdi:clock-start", None, False),
            SettingNumber(c, SET_MIN_RUN, "Marche minimale", 0, 240, 5, UnitOfTime.MINUTES, "mdi:timer-sand", None, True),
            SettingNumber(c, SET_COOLDOWN, "Délai de rallumage", 0, 120, 5, UnitOfTime.MINUTES, "mdi:timer-off-outline", None, True),
            SettingNumber(c, SET_POWER_PLAN, "Puissance de chauffe prévue (0 = apprise)", 0, 100, 5, "%", "mdi:fire", None, True),
            SettingNumber(c, SET_ADVANCE_MAX, "Avance maximale (Apprise)", 30, 360, 5, UnitOfTime.MINUTES, "mdi:clock-alert-outline", None, True),
            StoveSetpointNumber(c),
            StovePowerNumber(c),
        ]
    )


class SettingNumber(PoeleEntity, NumberEntity):
    """Réglage de l'intégration, persistant."""

    _attr_mode = NumberMode.BOX

    def __init__(self, controller, key, name, vmin, vmax, step, unit, icon, device_class, config) -> None:
        super().__init__(controller, key)
        self._key = key
        self._attr_name = name
        self._attr_native_min_value = vmin
        self._attr_native_max_value = vmax
        self._attr_native_step = step
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._attr_device_class = device_class
        if config:
            self._attr_entity_category = EntityCategory.CONFIG

    @property
    def native_value(self) -> float:
        return float(self.controller.settings[self._key])

    async def async_set_native_value(self, value: float) -> None:
        await self.controller.async_set_setting(self._key, value)


class StoveSetpointNumber(ProxyEntity, NumberEntity):
    """Consigne propre du poêle (Rika), utilisée en mode Confort."""

    _attr_name = "Consigne du poêle (Rika)"
    _attr_icon = "mdi:thermometer-lines"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = CLIMATE_MIN
    _attr_native_max_value = CLIMATE_MAX
    _attr_native_step = 1
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_device_class = NumberDeviceClass.TEMPERATURE

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "stove_setpoint", controller.climate)

    @property
    def native_value(self) -> float | None:
        state = self.source_state
        value = state.attributes.get("temperature") if state else None
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self.hass.services.async_call(
            "climate", "set_temperature",
            {"entity_id": self.controller.climate, "temperature": value}, blocking=True,
        )


class StovePowerNumber(ProxyEntity, NumberEntity):
    """Puissance du poêle en modes Auto et Manuel (30 à 100 %)."""

    _attr_name = "Puissance (Auto / Manuel)"
    _attr_icon = "mdi:fire"
    _attr_mode = NumberMode.BOX
    _attr_native_min_value = POWER_MIN
    _attr_native_max_value = POWER_MAX
    _attr_native_step = POWER_STEP
    _attr_native_unit_of_measurement = "%"

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "stove_power", controller.power)

    @property
    def native_value(self) -> float | None:
        state = self.source_state
        if state is None or state.state == STATE_UNKNOWN:
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    async def async_set_native_value(self, value: float) -> None:
        await self.hass.services.async_call(
            "number", "set_value",
            {"entity_id": self.controller.power, "value": value}, blocking=True,
        )
