"""Calendrier des plages de chauffe (créer / modifier / supprimer depuis l'interface)."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import uuid4

from homeassistant.components.calendar import (
    CalendarEntity,
    CalendarEntityFeature,
    CalendarEvent,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .controller import PoeleController
from .entity import PoeleEntity
from .schedule import StoredEvent


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([PoeleCalendar(hass.data[DOMAIN][entry.entry_id])])


def _as_datetime(value: Any, label: str) -> datetime:
    if isinstance(value, date) and not isinstance(value, datetime):
        raise ServiceValidationError(
            f"{label} : seuls les événements avec une heure sont pris en charge (pas « toute la journée »)."
        )
    if isinstance(value, str):
        value = dt_util.parse_datetime(value)
    if not isinstance(value, datetime):
        raise ServiceValidationError(f"{label} invalide.")
    return dt_util.as_local(value)


class PoeleCalendar(PoeleEntity, CalendarEntity):
    """Plages pendant lesquelles le poêle doit chauffer.

    Les modifications d'un événement récurrent s'appliquent à toute la série.
    """

    _attr_name = "Plages de chauffe"
    _attr_icon = "mdi:calendar-clock"
    _attr_supported_features = (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
    )

    def __init__(self, controller: PoeleController) -> None:
        super().__init__(controller, "calendar")

    @property
    def event(self) -> CalendarEvent | None:
        """Plage en cours, sinon la prochaine."""
        now = dt_util.now()
        for start, end, summary, uid in self.controller.occurrences:
            if end > now:
                return CalendarEvent(start=start, end=end, summary=summary, uid=uid)
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        events: list[CalendarEvent] = []
        by_uid = {ev.uid: ev for ev in self.controller.events.events}
        for start, end, summary, uid in self.controller.events.occurrences(start_date, end_date):
            source = by_uid.get(uid)
            events.append(
                CalendarEvent(
                    start=start,
                    end=end,
                    summary=summary,
                    description=source.description if source else None,
                    uid=uid,
                    rrule=source.rrule if source else None,
                )
            )
        return events

    async def async_create_event(self, **kwargs: Any) -> None:
        start = _as_datetime(kwargs.get("dtstart"), "Début")
        end = _as_datetime(kwargs.get("dtend"), "Fin")
        if end <= start:
            raise ServiceValidationError("La fin doit être après le début.")
        event = StoredEvent(
            uid=uuid4().hex,
            summary=kwargs.get("summary") or "Chauffe",
            start=start,
            end=end,
            rrule=kwargs.get("rrule") or None,
            description=kwargs.get("description"),
        )
        await self.controller.events.async_add(event)
        await self.controller.async_evaluate()

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        if not await self.controller.events.async_delete(uid):
            raise ServiceValidationError("Plage introuvable.")
        await self.controller.async_evaluate()

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        stored = self.controller.events.get(uid)
        if stored is None:
            raise ServiceValidationError("Plage introuvable.")
        if "summary" in event and event["summary"]:
            stored.summary = event["summary"]
        if "description" in event:
            stored.description = event["description"]
        if "rrule" in event:
            stored.rrule = event["rrule"] or None
        if "dtstart" in event:
            stored.start = _as_datetime(event["dtstart"], "Début")
        if "dtend" in event:
            stored.end = _as_datetime(event["dtend"], "Fin")
        if stored.end <= stored.start:
            raise ServiceValidationError("La fin doit être après le début.")
        await self.controller.events.async_update(stored)
        await self.controller.async_evaluate()
