"""Capteurs : état du poêle, planning, dernière décision, température de référence."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event

from .const import DOMAIN, SET_ANTICIPATION_MIN, SET_ANTICIPATION_MODE, SET_PILOTAGE
from .controller import PoeleController
from .entity import PoeleEntity, ProxyEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c: PoeleController = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            StoveStateSensor(c),
            ReferenceTemperatureSensor(c),
            NextStartSensor(c),
            EstimatedDurationSensor(c),
            WindowEndSensor(c),
            DecisionSensor(c),
            PelletsSensor(c),
            LearnedParamSensor(c, "learned_k", "Perte de la maison k (apprise)", "1/h", "mdi:home-thermometer-outline", lambda m, d: m.k, 4),
            LearnedParamSensor(c, "learned_rise", "Montée à 100 % (apprise)", "°C/h", "mdi:fireplace", lambda m, d: m.a100, 2),
            LearnedParamSensor(c, "learned_latency", "Latence d'allumage (apprise)", "min", "mdi:timer-sand", lambda m, d: m.latency, 0),
            LearnedParamSensor(c, "learned_tau", "Inertie de chauffe (apprise)", "min", "mdi:timer-sand-complete", lambda m, d: m.tau, 0),
            LearnedParamSensor(c, "learned_power", "Puissance habituelle (apprise)", "%", "mdi:fire", lambda m, d: d["power"], 0),
            LearningStatusSensor(c),
        ]
    )


class StoveStateSensor(ProxyEntity, SensorEntity):
    """Éteint / En veille / En chauffe / Extinction (état principal du poêle)."""

    _attr_name = "État du poêle"
    _attr_icon = "mdi:fire"

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "stove_state", controller.on_off)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                [self.controller.main_state_entity, self.controller.status],
                self._source_changed,
            )
        )

    @property
    def native_value(self) -> str | None:
        return self.controller.stove_label


class ReferenceTemperatureSensor(ProxyEntity, SensorEntity):
    """Température de la pièce utilisée par la régulation."""

    _attr_name = "Température de référence"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "reference_temperature", controller.room_temp_entity)

    @property
    def native_value(self) -> float | None:
        return self.controller.room_temperature


class NextStartSensor(PoeleEntity, SensorEntity):
    """Prochain allumage prévu, avec l'anticipation éventuelle."""

    _attr_name = "Prochain allumage prévu"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-start"

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "next_start")

    @property
    def native_value(self) -> datetime | None:
        return self.controller.decision.next_start


class EstimatedDurationSensor(PoeleEntity, SensorEntity):
    """Durée de chauffe estimée, poêle allumé maintenant, pour atteindre la consigne."""

    _attr_name = "Durée de chauffe estimée"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _attr_icon = "mdi:timer-outline"

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "estimated_duration")

    @property
    def native_value(self) -> int | None:
        return self.controller.estimate.get("minutes")

    @property
    def extra_state_attributes(self) -> dict:
        e = self.controller.estimate
        return {
            "parametres": e.get("parametres"),
            "chauffes_apprises": e.get("chauffes_apprises"),
            "k_perte_maison": e.get("k"),
            "montee_a_100_pct": e.get("rise_100"),
            "latence_min": e.get("latency"),
            "inertie_tau_min": e.get("tau"),
            "puissance_prevue_pct": e.get("power"),
            "temperature_exterieure": e.get("outdoor"),
            "temperature_salon": e.get("room"),
        }


class WindowEndSensor(PoeleEntity, SensorEntity):
    """Fin de la plage en cours (ou de la prochaine plage)."""

    _attr_name = "Fin de plage"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:clock-end"

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "window_end")

    @property
    def native_value(self) -> datetime | None:
        return self.controller.decision.window_end


class DecisionSensor(PoeleEntity, SensorEntity):
    """Dernière décision de la régulation, avec le détail en attributs."""

    _attr_name = "Dernière décision"
    _attr_icon = "mdi:head-cog-outline"

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "decision")

    @property
    def native_value(self) -> str:
        d = self.controller.decision
        return {"start": "Allumer", "stop": "Éteindre"}.get(d.action, "Aucune action")

    @property
    def extra_state_attributes(self) -> dict:
        d = self.controller.decision
        return {
            "raison": d.reason,
            "plage_active": d.in_window,
            "chauffe_souhaitee": d.heating_wanted,
            "pilotage_actif": bool(self.controller.settings[SET_PILOTAGE]),
            "plages_rika_actives": self.controller.rika_schedule_on,
            "commande_bloquee_par_plages_rika": bool(
                self.controller.settings[SET_PILOTAGE]
                and self.controller.blocked_by_rika
                and d.action != "none"
            ),
            "anticipation": self.controller.settings[SET_ANTICIPATION_MODE],
            "avance_minutes": self.controller.settings[SET_ANTICIPATION_MIN],
        }


class PelletsSensor(ProxyEntity, SensorEntity):
    """Pellets restants avant entretien (recopie du capteur Rika)."""

    _attr_name = "Pellets avant entretien"
    _attr_icon = "mdi:progress-wrench"

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "pellets", controller.pellets)

    @property
    def native_value(self) -> str | float | None:
        state = self.source_state
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            return float(state.state)
        except ValueError:
            return state.state

    @property
    def native_unit_of_measurement(self) -> str | None:
        state = self.source_state
        return state.attributes.get("unit_of_measurement") if state else None


class LearnedParamSensor(PoeleEntity, SensorEntity):
    """Un paramètre du modèle thermique, appris automatiquement."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, controller, key, name, unit, icon, getter, precision) -> None:
        super().__init__(controller, key)
        self._attr_name = name
        self._attr_native_unit_of_measurement = unit
        self._attr_icon = icon
        self._getter = getter
        self._attr_suggested_display_precision = precision

    @property
    def native_value(self) -> float:
        learning = self.controller.learning
        return float(self._getter(learning.model, learning.data))

    @property
    def extra_state_attributes(self) -> dict:
        d = self.controller.learning.data
        return {"chauffes_apprises": d["n_runs"], "nuits_apprises": d["n_k"]}


class LearningStatusSensor(PoeleEntity, SensorEntity):
    """Où en est l'apprentissage, avec l'historique des dernières chauffes analysées."""

    _attr_name = "État de l'apprentissage"
    _attr_icon = "mdi:school-outline"

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "learning_status")

    @property
    def native_value(self) -> str:
        n = self.controller.learning.n_runs
        if n == 0:
            return "Valeurs de départ"
        if n < 3:
            return f"En apprentissage ({n}/3 chauffes)"
        return "Calibré"

    @property
    def extra_state_attributes(self) -> dict:
        d = self.controller.learning.data
        return {
            "chauffes_retenues": d["n_runs"],
            "nuits_retenues": d["n_k"],
            "mesures_k": d["k_pairs"],
            "k_mis_a_jour": d["k_updated"],
            "chauffes_en_attente": len(d["pending"]),
            "amorce_sur_historique": d.get("bootstrapped"),
            "echantillons": len(self.controller.learning.samples),
            "derniere_analyse": d["last_fit"],
            "historique": d["history"],
        }
