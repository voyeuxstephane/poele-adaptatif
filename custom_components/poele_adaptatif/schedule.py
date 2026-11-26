"""Logique pure (sans Home Assistant) : plages de chauffe, anticipation, décision.

Ce module ne dépend que de la bibliothèque standard et de python-dateutil afin
de pouvoir être testé hors de Home Assistant (voir tests/).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from dateutil import rrule as du_rrule

Window = tuple[datetime, datetime]
Occurrence = tuple[datetime, datetime, str, str]  # début, fin, titre, uid


# --------------------------------------------------------------------------- #
# Événements du calendrier
# --------------------------------------------------------------------------- #
@dataclass
class StoredEvent:
    """Plage de chauffe stockée (éventuellement récurrente via RRULE)."""

    uid: str
    summary: str
    start: datetime  # avec fuseau
    end: datetime  # avec fuseau
    rrule: str | None = None
    description: str | None = None

    def to_dict(self) -> dict[str, Any]:
        tz_key = getattr(self.start.tzinfo, "key", None) or "UTC"
        return {
            "uid": self.uid,
            "summary": self.summary,
            # heure locale « murale » + nom du fuseau : l'heure reste stable
            # lors des changements d'heure été/hiver pour les récurrences
            "start": self.start.replace(tzinfo=None).isoformat(),
            "end": self.end.replace(tzinfo=None).isoformat(),
            "tz": tz_key,
            "rrule": self.rrule,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "StoredEvent":
        tz = ZoneInfo(data.get("tz") or "UTC")
        return cls(
            uid=data["uid"],
            summary=data.get("summary") or "Chauffe",
            start=datetime.fromisoformat(data["start"]).replace(tzinfo=tz),
            end=datetime.fromisoformat(data["end"]).replace(tzinfo=tz),
            rrule=data.get("rrule") or None,
            description=data.get("description"),
        )


def occurrences(
    event: StoredEvent, window_start: datetime, window_end: datetime
) -> list[Window]:
    """Occurrences (début, fin) de l'événement qui recoupent [window_start, window_end]."""
    duration = event.end - event.start
    if duration <= timedelta(0):
        return []
    if not event.rrule:
        if event.end > window_start and event.start < window_end:
            return [(event.start, event.end)]
        return []
    try:
        rule = du_rrule.rrulestr(event.rrule, dtstart=event.start)
        starts = rule.between(window_start - duration, window_end, inc=True)
    except (ValueError, TypeError):
        return []
    return [
        (s, s + duration)
        for s in starts
        if s + duration > window_start and s < window_end
    ]


def all_occurrences(
    events: list[StoredEvent], window_start: datetime, window_end: datetime
) -> list[Occurrence]:
    out: list[Occurrence] = []
    for ev in events:
        for s, e in occurrences(ev, window_start, window_end):
            out.append((s, e, ev.summary, ev.uid))
    out.sort(key=lambda o: o[0])
    return out


def merge_windows(
    windows: list[Window], gap: timedelta = timedelta(0)
) -> list[Window]:
    """Fusionne les plages qui se chevauchent ou se touchent."""
    merged: list[Window] = []
    for start, end in sorted(windows, key=lambda w: w[0]):
        if merged and start <= merged[-1][1] + gap:
            if end > merged[-1][1]:
                merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    return merged


def default_events(tz: tzinfo) -> list[StoredEvent]:
    """Plages de départ, lues sur la capture de l'appli Rika (à ajuster)."""

    def at(day: int, hour: int, minute: int) -> datetime:
        return datetime(2026, 11, day, hour, minute, tzinfo=tz)

    week = "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR"
    weekend = "FREQ=WEEKLY;BYDAY=SA,SU"
    return [
        StoredEvent("defaut-semaine-matin", "Chauffe matin (semaine)", at(16, 5, 0), at(16, 6, 40), week),
        StoredEvent("defaut-semaine-soir", "Chauffe après-midi et soir (semaine)", at(16, 15, 0), at(16, 22, 0), week),
        StoredEvent("defaut-weekend", "Chauffe week-end", at(21, 5, 30), at(21, 22, 0), weekend),
    ]


# --------------------------------------------------------------------------- #
# Décision
# --------------------------------------------------------------------------- #
@dataclass
class Decision:
    """Résultat d'une évaluation (affiché dans le capteur « Dernière décision »)."""

    action: str  # "none" | "start" | "stop"
    reason: str
    heating_wanted: bool = False
    in_window: bool = False
    next_start: datetime | None = None  # allumage prévu (avec anticipation)
    window_end: datetime | None = None  # fin de la plage en cours ou à venir
    window_start: datetime | None = None  # début de la plage en cours ou à venir
    anticipating: bool = False  # allumage (ou maintien) pour la prochaine plage


def decide(
    now: datetime,
    windows: list[Window],
    *,
    stove_on: bool,
    started_by_us: bool,
    room_temp: float | None,
    consigne: float,
    hysteresis: float,
    anticipation_minutes: int,
    min_run_minutes: int,
    cooldown_minutes: int,
    last_start: datetime | None,
    last_stop: datetime | None,
    anticipating_for: datetime | None = None,
) -> Decision:
    """Décide s'il faut allumer, éteindre ou ne rien faire.

    Règles de la version 0.1 (volontairement simples, sans simulation) :
    - on chauffe pendant les plages, et pendant l'avance d'anticipation avant
      la prochaine plage ;
    - allumage seulement si la pièce est sous consigne - hystérésis ;
    - pas de rallumage dans le délai de rallumage après un arrêt ;
    - pas d'allumage court : si la plage en cours se termine dans moins de la
      marche minimale, on n'allume pas ;
    - extinction à la fin de plage, uniquement si c'est l'intégration qui a
      allumé, et pas avant la marche minimale ;
    - pendant la plage, l'arrêt à consigne + hystérésis reste géré par le
      thermostat du poêle (mode Confort).
    """
    advance = timedelta(minutes=max(0, int(anticipation_minutes)))
    min_run = timedelta(minutes=max(0, int(min_run_minutes)))
    cooldown = timedelta(minutes=max(0, int(cooldown_minutes)))

    current = next((w for w in windows if w[0] <= now < w[1]), None)
    upcoming = next((w for w in windows if w[0] > now), None)
    prestart = (
        advance > timedelta(0)
        and current is None
        and upcoming is not None
        and now >= upcoming[0] - advance
    )
    # Maintien : si l'intégration a allumé pour cette plage à venir, on garde le
    # poêle allumé même si l'estimation de durée a diminué entre-temps.
    holding = (
        stove_on
        and started_by_us
        and current is None
        and upcoming is not None
        and anticipating_for is not None
        and anticipating_for == upcoming[0]
    )
    wanted = current is not None or prestart or holding

    if current is not None:
        next_start = None
        window_end = current[1]
        window_start = current[0]
    elif upcoming is not None:
        next_start = upcoming[0] - advance
        window_end = upcoming[1]
        window_start = upcoming[0]
    else:
        next_start = None
        window_end = None
        window_start = None

    base = {
        "heating_wanted": wanted,
        "in_window": current is not None,
        "next_start": next_start,
        "window_end": window_end,
        "window_start": window_start,
        "anticipating": current is None and (prestart or holding),
    }

    if wanted and not stove_on:
        if last_stop is not None and now - last_stop < cooldown:
            minutes = int((now - last_stop).total_seconds() // 60)
            return Decision(
                "none",
                f"rallumage différé : arrêt il y a {minutes} min (délai {int(cooldown.total_seconds() // 60)} min)",
                **base,
            )
        if room_temp is None:
            return Decision("none", "température de référence indisponible", **base)
        if room_temp >= consigne - hysteresis:
            return Decision(
                "none",
                f"température suffisante ({room_temp:.1f} °C ≥ {consigne - hysteresis:.1f} °C)",
                **base,
            )
        if current is not None and current[1] - now < min_run:
            return Decision(
                "none",
                "plage presque terminée : allumage court évité",
                **base,
            )
        why = "début de plage" if current is not None else f"anticipation de {int(advance.total_seconds() // 60)} min"
        return Decision("start", f"allumage ({why})", **base)

    if not wanted and stove_on and started_by_us:
        if last_start is not None and now - last_start < min_run:
            return Decision("none", "marche minimale non atteinte", **base)
        return Decision("stop", "fin de plage", **base)

    if wanted:
        return Decision("none", "plage active, rien à faire", **base)
    return Decision("none", "hors plage, rien à faire", **base)


# --------------------------------------------------------------------------- #
# Durée de chauffe estimée (anticipation apprise)
# --------------------------------------------------------------------------- #
def estimate_heating_minutes(
    t_room: float,
    target: float,
    t_out: float,
    *,
    a100: float,
    k: float,
    power_pct: float,
    latency_min: float,
    max_minutes: int = 480,
) -> int:
    """Minutes nécessaires, poêle allumé maintenant, pour atteindre la consigne.

    Modèle appris dans Home Assistant (même équation que la simulation) :
        pente = a100 * puissance / 100 - k * (T - T_ext)      [°C/h]
    Pendant la latence d'allumage (le salon ne chauffe pas encore) seule la
    perte s'applique. Renvoie ``max_minutes`` si la consigne est inatteignable.
    """
    if t_room >= target:
        return 0
    gain = max(0.0, a100) * max(0.0, power_pct) / 100.0
    if k > 0 and t_out + gain / k <= target:
        return max_minutes  # température d'équilibre sous la consigne
    t = t_room
    for minute in range(1, max_minutes + 1):
        heating = minute > latency_min
        rate = (gain if heating else 0.0) - k * (t - t_out)
        t += rate / 60.0
        if t >= target:
            return minute
    return max_minutes
