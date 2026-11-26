"""Amorçage de l'apprentissage à partir de l'historique Home Assistant (logique pure).

Rejoue les changements d'état enregistrés (recorder) minute par minute pour reconstituer les
mêmes échantillons que ceux pris en direct : [horodatage, salon, extérieur, puissance, allumé, nuit].
"""
from __future__ import annotations

from bisect import bisect_right
from datetime import datetime
from typing import Any, Iterable

from .const import BURNING_STATES

BAD = ("unknown", "unavailable", "", None)

Series = dict[str, list[tuple[float, str]]]


def _value_at(points: list[tuple[float, str]], keys: list[float], ts: float) -> str | None:
    i = bisect_right(keys, ts) - 1
    if i < 0:
        return None
    v = points[i][1]
    return None if v in BAD else v


def _num(v: str | None) -> float | None:
    try:
        return float(v) if v is not None else None
    except ValueError:
        return None


def power_from(main: str | None, fan: float | None, feed: float | None) -> float:
    """Même formule que PoeleController.power_relative."""
    if main != "4":
        return 0.0
    if fan is not None and 1000 < fan < 1400:
        value = (fan - 640) / 1.3
    elif feed is not None:
        value = feed
    else:
        return 0.0
    return round(min(max(value, 0.0), 525.0) / 5.25, 1)


def build_samples(
    series: Series,
    room: str,
    outdoor: str,
    main: str,
    fan: str,
    feed: str,
    t0: float,
    t1: float,
    sun: str = "sun.sun",
) -> list[list[Any]]:
    """Un échantillon par minute entre t0 et t1 (timestamps), à partir des changements d'état."""
    pts = {e: sorted(series.get(e, [])) for e in (room, outdoor, main, fan, feed, sun)}
    keys = {e: [p[0] for p in v] for e, v in pts.items()}
    out: list[list[Any]] = []
    start = int(t0 // 60 * 60)
    for ts in range(start, int(t1) + 1, 60):
        m = _value_at(pts[main], keys[main], ts)
        if m is None and not pts[main]:
            continue
        r = _num(_value_at(pts[room], keys[room], ts))
        if r is None:
            continue  # pas de température du salon : l'échantillon est inutile
        o = _num(_value_at(pts[outdoor], keys[outdoor], ts))
        f = _num(_value_at(pts[fan], keys[fan], ts))
        d = _num(_value_at(pts[feed], keys[feed], ts))
        s = _value_at(pts[sun], keys[sun], ts)
        if s in ("above_horizon", "below_horizon"):
            night = s == "below_horizon"
        else:
            hour = datetime.fromtimestamp(ts).hour
            night = hour >= 22 or hour < 6
        out.append(
            [ts, r, o, power_from(m, f, d), 1 if m in BURNING_STATES else 0, 1 if night else 0]
        )
    return out


def runs_from_samples(samples: Iterable[list[Any]], min_minutes: int = 10) -> list[tuple[int, int]]:
    """Chauffes (début, fin) en timestamps : séquences d'échantillons allumés consécutifs (trous ≤ 5 min)."""
    runs: list[tuple[int, int]] = []
    start = last = None
    for ts, _r, _o, _p, burning, _n in sorted(samples, key=lambda s: s[0]):
        if burning:
            if start is None:
                start = last = ts
            elif ts - last <= 5 * 60:
                last = ts
            else:
                runs.append((start, last))
                start = last = ts
        elif start is not None and ts - last > 5 * 60:
            runs.append((start, last))
            start = last = None
    if start is not None and last is not None:
        runs.append((start, last))
    return [(a, b + 60) for a, b in runs if (b - a) / 60 >= min_minutes]
