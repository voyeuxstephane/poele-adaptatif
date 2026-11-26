"""Stockage des plages de chauffe (calendrier)."""
from __future__ import annotations

import logging
from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, STORAGE_VERSION
from .schedule import Occurrence, StoredEvent, all_occurrences, default_events

_LOGGER = logging.getLogger(__name__)


class EventStore:
    """Plages de chauffe persistées dans .storage (une entrée par intégration)."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.events.{entry_id}")
        self._events: dict[str, StoredEvent] = {}

    async def async_load(self) -> None:
        data = await self._store.async_load()
        if data is None:
            # Premier démarrage : plages issues de la capture de l'appli Rika
            for event in default_events(dt_util.DEFAULT_TIME_ZONE):
                self._events[event.uid] = event
            await self._async_save()
            return
        for item in data.get("events", []):
            try:
                event = StoredEvent.from_dict(item)
            except (KeyError, ValueError) as err:
                _LOGGER.warning("Plage de chauffe ignorée (%s) : %s", err, item)
                continue
            self._events[event.uid] = event

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"events": [event.to_dict() for event in self._events.values()]}
        )

    @property
    def events(self) -> list[StoredEvent]:
        return list(self._events.values())

    def get(self, uid: str) -> StoredEvent | None:
        return self._events.get(uid)

    def occurrences(self, start: datetime, end: datetime) -> list[Occurrence]:
        return all_occurrences(self.events, start, end)

    async def async_add(self, event: StoredEvent) -> None:
        self._events[event.uid] = event
        await self._async_save()

    async def async_update(self, event: StoredEvent) -> None:
        self._events[event.uid] = event
        await self._async_save()

    async def async_delete(self, uid: str) -> bool:
        if uid not in self._events:
            return False
        del self._events[uid]
        await self._async_save()
        return True
