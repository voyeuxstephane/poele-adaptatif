"""Contrôleur central : réglages, état du poêle, décisions et commandes."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Callable

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    BURNING_STATES,
    ANTICIPATION_FIXED,
    ANTICIPATION_LEARNED,
    CLIMATE_MAX,
    CLIMATE_MIN,
    COMMAND_LOCK_MINUTES,
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
    DEFAULT_SETTINGS,
    DOMAIN,
    FALLBACK_OUTDOOR,
    MODE_AUTO,
    MODE_CONFORT,
    MODE_MANUEL,
    PENDING_START_MINUTES,
    POWER_MAX,
    POWER_MIN,
    POWER_STEP,
    SET_ADVANCE_MAX,
    SET_ANTICIPATION_MIN,
    SET_ANTICIPATION_MODE,
    SET_COOLDOWN,
    SET_CONSIGNE,
    SET_HYSTERESIS,
    SET_MIN_RUN,
    SET_PILOTAGE,
    SET_POWER_PLAN,
    STORAGE_VERSION,
)
from . import learner as lr
from .learning import LearningManager
from .schedule import Decision, Occurrence, decide, merge_windows
from .store import EventStore

_LOGGER = logging.getLogger(__name__)


class PoeleController:
    """Coordonne réglages, calendrier, état du poêle et commandes."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        cfg = {**DEFAULT_ENTITIES, **entry.data, **entry.options}
        self.climate: str = cfg[CONF_CLIMATE]
        self.on_off: str = cfg[CONF_ON_OFF]
        self.heating_times: str = cfg[CONF_HEATING_TIMES]
        self.power: str = cfg[CONF_POWER]
        self.status: str = cfg[CONF_STATUS]
        self.pellets: str = cfg[CONF_PELLETS]
        self.room_temp_entity: str = cfg[CONF_ROOM_TEMP]
        self.main_state_entity: str = cfg[CONF_MAIN_STATE]
        self.outdoor_entity: str = cfg[CONF_OUTDOOR_TEMP]
        self.fan_entity: str = cfg[CONF_FAN]
        self.diag_entity: str = cfg[CONF_DIAG]

        self.settings: dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.runtime: dict[str, Any] = {
            "last_start": None,
            "last_stop": None,
            "started_by_us": False,
            "anticipating_for": None,
        }
        self.estimate: dict[str, Any] = {}
        self.events = EventStore(hass, entry.entry_id)
        self.learning = LearningManager(hass, entry.entry_id)
        self.decision = Decision("none", "pas encore évalué")
        self.occurrences: list[Occurrence] = []
        self.windows: list[tuple[datetime, datetime]] = []

        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.settings.{entry.entry_id}")
        self._listeners: set[Callable[[], None]] = set()
        self._unsubs: list[Callable[[], None]] = []
        self._pending_start = False
        self._pending_since: datetime | None = None
        self.blocked_by_rika = False
        self._last_command: datetime | None = None

    # ------------------------------------------------------------------ #
    # Cycle de vie
    # ------------------------------------------------------------------ #
    async def async_load(self) -> None:
        data = await self._store.async_load() or {}
        for key in DEFAULT_SETTINGS:
            if key in data.get("settings", {}):
                self.settings[key] = data["settings"][key]
        self.runtime.update(data.get("runtime", {}))
        # 0.3 : la puissance de chauffe est apprise (0 = auto) ; 90 était l'ancienne valeur par défaut
        if self.settings.get(SET_POWER_PLAN) == 90:
            self.settings[SET_POWER_PLAN] = 0
        await self.events.async_load()
        await self.learning.async_load()
        self._remove_obsolete_entities()

    def _remove_obsolete_entities(self) -> None:
        """Supprime les entités qui n'existent plus (la latence est maintenant apprise)."""
        from homeassistant.helpers import entity_registry as er

        registry = er.async_get(self.hass)
        for platform, key in (("number", "latency_minutes"),):
            entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{self.entry.entry_id}_{key}")
            if entity_id:
                registry.async_remove(entity_id)

    async def async_start(self) -> None:
        self._unsubs.append(
            async_track_time_interval(self.hass, self._async_tick, timedelta(minutes=1))
        )
        self._unsubs.append(
            async_track_state_change_event(
                self.hass,
                [
                    self.on_off,
                    self.main_state_entity,
                    self.heating_times,
                    self.room_temp_entity,
                    self.outdoor_entity,
                ],
                self._state_changed,
            )
        )
        self.learning.configure_history(
            self.room_temp_entity, self.outdoor_entity, self.main_state_entity,
            self.fan_entity, self.diag_entity,
        )
        if self.learning.data.get("bootstrapped") is None and "recorder" in self.hass.config.components:
            self.hass.async_create_background_task(self.async_bootstrap(), "poele_adaptatif_bootstrap")
        await self.async_evaluate()

    async def async_bootstrap(self) -> dict[str, Any]:
        report = await self.learning.async_bootstrap(dt_util.now())
        self._notify()
        return report

    async def async_stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        self.learning._maybe_save(dt_util.now(), force=True)

    def _data_to_save(self) -> dict[str, Any]:
        return {"settings": self.settings, "runtime": self.runtime}

    def _save(self) -> None:
        self._store.async_delay_save(self._data_to_save, 1)

    # ------------------------------------------------------------------ #
    # Écouteurs (entités)
    # ------------------------------------------------------------------ #
    @callback
    def async_add_listener(self, update: Callable[[], None]) -> Callable[[], None]:
        self._listeners.add(update)

        @callback
        def remove() -> None:
            self._listeners.discard(update)

        return remove

    @callback
    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    # ------------------------------------------------------------------ #
    # Lecture de l'état du poêle
    # ------------------------------------------------------------------ #
    def _state(self, entity_id: str) -> str | None:
        state = self.hass.states.get(entity_id)
        if state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        return state.state

    @property
    def stove_enabled(self) -> bool:
        """Interrupteur « marche / arrêt » Rika : le poêle est activé (même s'il attend sa planification)."""
        return self._state(self.on_off) == STATE_ON

    @property
    def burning(self) -> bool | None:
        """Le poêle s'allume ou brûle (états principaux 2 à 5). None si inconnu."""
        state = self._state(self.main_state_entity)
        if state is None:
            return None
        return state in BURNING_STATES

    @property
    def stove_on(self) -> bool:
        """Vrai si le poêle est réellement allumé ; sinon repli sur l'interrupteur."""
        burning = self.burning
        return self.stove_enabled if burning is None else burning

    @property
    def rika_schedule_on(self) -> bool:
        return self._state(self.heating_times) == STATE_ON

    @property
    def room_temperature(self) -> float | None:
        value = self._state(self.room_temp_entity)
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None

    @property
    def outdoor_temperature(self) -> float | None:
        return self._float(self.outdoor_entity)

    @property
    def stove_label(self) -> str | None:
        """Éteint / En veille / En chauffe / Extinction."""
        on = self._state(self.on_off)
        if on is None:
            return None
        if on != STATE_ON:
            return "Éteint"
        main = self._state(self.main_state_entity)
        if main in BURNING_STATES:
            return "En chauffe"
        if main == "6":
            return "Extinction"
        if main is None and self._state(self.status) not in ("standby", "external_request"):
            return "En chauffe"
        return "En veille"

    def power_relative(self) -> float:
        """Puissance réelle du poêle en % du maximum (100 % = vis à 525 ‰), 0 hors marche."""
        if self._state(self.main_state_entity) != "4":
            return 0.0
        fan = self._float(self.fan_entity)
        feed = self._float(self.diag_entity)
        if fan is not None and 1000 < fan < 1400:
            value = (fan - 640) / 1.3
        elif feed is not None:
            value = feed
        else:
            return 0.0
        return round(min(max(value, 0.0), 525.0) / 5.25, 1)

    def _is_night(self, now: datetime) -> bool:
        sun = self.hass.states.get("sun.sun")
        if sun is not None and sun.state in ("above_horizon", "below_horizon"):
            return sun.state == "below_horizon"
        return now.hour >= 22 or now.hour < 6

    def _float(self, entity_id: str) -> float | None:
        value = self._state(entity_id)
        try:
            return float(value) if value is not None else None
        except ValueError:
            return None

    def _compute_estimate(self) -> dict[str, Any]:
        """Durée de chauffe estimée, poêle allumé maintenant, jusqu'à la consigne."""
        model = self.learning.model
        out = self.outdoor_temperature
        out = out if out is not None else FALLBACK_OUTDOOR
        power = float(self.settings[SET_POWER_PLAN]) or self.learning.power
        t_room = self.room_temperature
        minutes = None
        if t_room is not None:
            minutes = lr.minutes_to_reach(
                t_room, float(self.settings[SET_CONSIGNE]), out, model, power
            )
        return {
            "minutes": minutes,
            "k": round(model.k, 4),
            "rise_100": round(model.a100, 2),
            "latency": round(model.latency),
            "tau": round(model.tau),
            "power": round(power),
            "outdoor": out,
            "room": t_room,
            "parametres": self.learning.confidence,
            "chauffes_apprises": self.learning.n_runs,
        }

    def _last(self, key: str) -> datetime | None:
        raw = self.runtime.get(key)
        if not raw:
            return None
        try:
            return dt_util.as_local(datetime.fromisoformat(raw))
        except ValueError:
            return None

    # ------------------------------------------------------------------ #
    # Réglages
    # ------------------------------------------------------------------ #
    async def async_set_setting(self, key: str, value: Any) -> None:
        self.settings[key] = value
        self._save()
        await self.async_evaluate()

    # ------------------------------------------------------------------ #
    # Évaluation et décisions automatiques
    # ------------------------------------------------------------------ #
    async def _async_tick(self, now: datetime) -> None:
        now = dt_util.as_local(now)
        self.learning.record(
            now,
            self.room_temperature,
            self._float(self.outdoor_entity),
            self.power_relative(),
            bool(self.burning),
            self._is_night(now),
        )
        changed = await self.learning.async_process(now)
        await self.async_evaluate(now)
        if changed:
            self._notify()

    @callback
    def _state_changed(self, event: Event) -> None:
        entity_id = event.data["entity_id"]
        old = event.data.get("old_state")
        new = event.data.get("new_state")
        if (
            entity_id == self.main_state_entity
            and old is not None
            and new is not None
            and old.state != new.state
            and old.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
            and new.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN)
        ):
            was = old.state in BURNING_STATES
            now_burning = new.state in BURNING_STATES
            now = dt_util.now()
            if now_burning and not was:
                self.runtime["last_start"] = now.isoformat()
                pending = (
                    self._pending_start
                    and self._pending_since is not None
                    and now - self._pending_since < timedelta(minutes=PENDING_START_MINUTES)
                )
                self.runtime["started_by_us"] = bool(pending)
                self._pending_start = False
                self._save()
            elif was and not now_burning:
                self.learning.on_run_end(self._last("last_start"), now)
                self.runtime["last_stop"] = now.isoformat()
                self.runtime["started_by_us"] = False
                self.runtime["anticipating_for"] = None
                self._save()
        self.hass.async_create_task(self.async_evaluate())

    async def async_evaluate(self, now: datetime | None = None) -> None:
        now = dt_util.now() if now is None else dt_util.as_local(now)
        self.occurrences = self.events.occurrences(
            now - timedelta(days=1), now + timedelta(days=4)
        )
        self.windows = merge_windows([(s, e) for s, e, _, _ in self.occurrences])

        self.estimate = self._compute_estimate()
        mode = self.settings[SET_ANTICIPATION_MODE]
        if mode == ANTICIPATION_FIXED:
            anticipation = int(self.settings[SET_ANTICIPATION_MIN])
        elif mode == ANTICIPATION_LEARNED:
            # allumage « au plus juste » : durée estimée pour atteindre la consigne
            minutes = self.estimate.get("minutes")
            anticipation = int(self.settings[SET_ADVANCE_MAX]) if minutes is None else min(
                int(self.settings[SET_ADVANCE_MAX]), int(minutes)
            )
        else:
            anticipation = 0
        anticipating_for = None
        if self.runtime.get("anticipating_for"):
            try:
                anticipating_for = dt_util.as_local(datetime.fromisoformat(self.runtime["anticipating_for"]))
            except ValueError:
                anticipating_for = None
        self.decision = decide(
            now,
            self.windows,
            stove_on=self.stove_on,
            started_by_us=bool(self.runtime.get("started_by_us")),
            room_temp=self.room_temperature,
            consigne=float(self.settings[SET_CONSIGNE]),
            hysteresis=float(self.settings[SET_HYSTERESIS]),
            anticipation_minutes=int(anticipation),
            min_run_minutes=int(self.settings[SET_MIN_RUN]),
            cooldown_minutes=int(self.settings[SET_COOLDOWN]),
            last_start=self._last("last_start"),
            last_stop=self._last("last_stop"),
            anticipating_for=anticipating_for,
        )
        self.blocked_by_rika = self.rika_schedule_on
        if (
            self.settings[SET_PILOTAGE]
            and self.decision.action != "none"
            and not self.blocked_by_rika
        ):
            await self._async_execute(self.decision, now)
        self._notify()

    async def _async_execute(self, decision: Decision, now: datetime) -> None:
        if self._last_command is not None and now - self._last_command < timedelta(
            minutes=COMMAND_LOCK_MINUTES
        ):
            return
        self._last_command = now
        try:
            if decision.action == "start":
                if decision.anticipating and decision.window_start is not None:
                    self.runtime["anticipating_for"] = decision.window_start.isoformat()
                else:
                    self.runtime["anticipating_for"] = None
                self._save()
                await self._async_start_stove()
            elif decision.action == "stop":
                await self._async_stop_stove()
        except HomeAssistantError as err:
            _LOGGER.error("Commande automatique du poêle en échec : %s", err)

    async def _async_start_stove(self) -> None:
        """Allume en mode Confort avec la consigne ; le poêle module et s'arrête seul."""
        _LOGGER.info("Allumage automatique du poêle : %s", self.decision.reason)
        self._pending_start = True
        self._pending_since = dt_util.now()
        climate = self.hass.states.get(self.climate)
        if climate is not None and climate.attributes.get("preset_mode") != "comfort":
            await self._call("climate", "set_preset_mode", {"entity_id": self.climate, "preset_mode": "comfort"})
        target = min(CLIMATE_MAX, max(CLIMATE_MIN, round(float(self.settings[SET_CONSIGNE]))))
        if climate is None or climate.attributes.get("temperature") != float(target):
            await self._call("climate", "set_temperature", {"entity_id": self.climate, "temperature": target})
        if not self.stove_enabled:
            await self._call("switch", "turn_on", {"entity_id": self.on_off})

    async def _async_stop_stove(self) -> None:
        # Volontairement une seule commande : l'intégration Rika remet « on » à
        # chaque commande, donc rien ne doit être envoyé après l'arrêt.
        _LOGGER.info("Extinction automatique du poêle : %s", self.decision.reason)
        await self._call("switch", "turn_off", {"entity_id": self.on_off})

    async def _call(self, domain: str, service: str, data: dict[str, Any]) -> None:
        await self.hass.services.async_call(domain, service, data, blocking=True)

    # ------------------------------------------------------------------ #
    # Commandes manuelles (reprennent celles de la carte du dashboard)
    # ------------------------------------------------------------------ #
    async def async_set_mode(self, mode: str) -> None:
        """Confort / Auto / Manuel : même logique que « Poêle – commandes dashboard »."""
        if mode == MODE_CONFORT:
            await self._call("climate", "set_preset_mode", {"entity_id": self.climate, "preset_mode": "comfort"})
            return
        if mode in (MODE_AUTO, MODE_MANUEL):
            for _ in range(2):
                climate = self.hass.states.get(self.climate)
                if climate is not None and climate.attributes.get("preset_mode") == "comfort":
                    await self._call("climate", "set_preset_mode", {"entity_id": self.climate, "preset_mode": "none"})
                    await asyncio.sleep(1)
            if mode == MODE_MANUEL:
                await self._call("switch", "turn_off", {"entity_id": self.heating_times})

    @property
    def mode(self) -> str | None:
        climate = self.hass.states.get(self.climate)
        if climate is None or climate.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        if climate.attributes.get("preset_mode") == "comfort":
            return MODE_CONFORT
        return MODE_AUTO if self._state(self.heating_times) == STATE_ON else MODE_MANUEL

    async def async_adjust(self, sens: int) -> None:
        """Boutons + / − : consigne du poêle en Confort, sinon puissance par pas de 5 %."""
        climate = self.hass.states.get(self.climate)
        if climate is not None and climate.attributes.get("preset_mode") == "comfort":
            current = float(climate.attributes.get("temperature") or 20)
            target = min(CLIMATE_MAX, max(CLIMATE_MIN, current + sens))
            await self._call("climate", "set_temperature", {"entity_id": self.climate, "temperature": target})
        else:
            try:
                current_power = int(float(self._state(self.power) or POWER_MIN))
            except ValueError:
                current_power = POWER_MIN
            target_power = min(POWER_MAX, max(POWER_MIN, current_power + POWER_STEP * sens))
            await self._call("number", "set_value", {"entity_id": self.power, "value": target_power})
