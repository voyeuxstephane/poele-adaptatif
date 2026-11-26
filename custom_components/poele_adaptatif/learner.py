"""Apprentissage thermique du salon (logique pure, sans Home Assistant).

Modèle (identique à la simulation) :

    T'(t) = a100 * x(t) - k * (T(t) - T_ext(t))                    [°C/h]
    x(t)  = puissance relative (0..1) retardée de ``latency`` minutes puis lissée
            par un filtre du 1er ordre de constante ``tau`` minutes

- ``k``        perte de la maison, apprise la nuit, poêle éteint depuis longtemps ;
- ``a100``     montée brute à 100 % de puissance ;
- ``latency``  délai avant que le salon réagisse à l'allumage ;
- ``tau``      inertie : le poêle continue de chauffer après son arrêt (chaleur résiduelle).

L'ajustement de (a100, latency, tau) se fait après chaque chauffe. Comme le système est
linéaire, ``a100`` s'obtient en forme fermée pour chaque couple (latency, tau) ; seuls
latency et tau sont cherchés sur une grille. Aucune dépendance externe.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

MIN_A, MAX_A = 0.3, 4.0
MIN_K, MAX_K = 0.005, 0.08
LATENCY_GRID = [0, 5, 10, 15, 20, 25, 30, 40]
TAU_GRID = [0, 5, 10, 20, 30, 45, 60]


@dataclass
class Model:
    a100: float = 1.6
    k: float = 0.02
    latency: float = 15.0
    tau: float = 20.0

    def as_dict(self) -> dict[str, float]:
        return {"a100": self.a100, "k": self.k, "latency": self.latency, "tau": self.tau}


@dataclass
class Fit:
    a100: float
    latency: float
    tau: float
    rmse: float
    n_points: int


# --------------------------------------------------------------------------- #
# Simulation
# --------------------------------------------------------------------------- #
def _lagged_input(power_pct: Sequence[float], latency: int, tau: float) -> list[float]:
    """Puissance relative (0..1) après délai puis filtre du 1er ordre, une valeur par minute."""
    n = len(power_pct)
    x = 0.0
    out: list[float] = []
    for i in range(n):
        j = i - latency
        u = power_pct[j] / 100.0 if j >= 0 else 0.0
        if tau > 1:
            x += (u - x) / tau
        else:
            x = u
        out.append(x)
    return out


def forced_response(power_pct: Sequence[float], latency: int, tau: float, k: float) -> list[float]:
    """Réponse de T à une montée de 1 °C/h par unité de puissance, départ à 0 (pas de 1 min)."""
    x = _lagged_input(power_pct, latency, tau)
    tf = 0.0
    out: list[float] = []
    for xi in x:
        out.append(tf)
        tf += (xi - k * tf) / 60.0
    return out


def free_response(t0: float, t_out: Sequence[float], k: float) -> list[float]:
    """Refroidissement libre depuis t0 (poêle éteint)."""
    t = t0
    out: list[float] = []
    for to in t_out:
        out.append(t)
        t += -k * (t - to) / 60.0
    return out


def simulate(
    t0: float, t_out: Sequence[float], power_pct: Sequence[float], model: Model
) -> list[float]:
    """Température simulée (1 valeur par minute)."""
    free = free_response(t0, t_out, model.k)
    forced = forced_response(power_pct, int(round(model.latency)), model.tau, model.k)
    return [f + model.a100 * g for f, g in zip(free, forced)]


# --------------------------------------------------------------------------- #
# Ajustement d'une chauffe
# --------------------------------------------------------------------------- #
def fit_run(
    room: Sequence[float | None],
    t_out: Sequence[float],
    power_pct: Sequence[float],
    k: float,
    *,
    min_points: int = 90,
) -> Fit | None:
    """Ajuste (a100, latency, tau) sur une série d'une valeur par minute.

    ``room`` peut contenir des None (points ignorés). Renvoie None si la série est
    inexploitable ou si l'ajustement sort des bornes.
    """
    obs = [(i, v) for i, v in enumerate(room) if v is not None]
    if len(obs) < min_points or len(room) != len(t_out) or len(room) != len(power_pct):
        return None
    t0 = obs[0][1]
    # on aligne la simulation sur le premier point observé
    start = obs[0][0]
    to = list(t_out[start:])
    pw = list(power_pct[start:])
    obs = [(i - start, v) for i, v in obs]
    free = free_response(t0, to, k)

    best: Fit | None = None
    for latency in LATENCY_GRID:
        for tau in TAU_GRID:
            forced = forced_response(pw, latency, tau, k)
            num = sum((v - free[i]) * forced[i] for i, v in obs)
            den = sum(forced[i] * forced[i] for i, _ in obs)
            if den <= 1e-9:
                continue
            a = min(MAX_A, max(MIN_A, num / den))
            sse = sum((v - free[i] - a * forced[i]) ** 2 for i, v in obs)
            rmse = (sse / len(obs)) ** 0.5
            if best is None or rmse < best.rmse:
                best = Fit(a, float(latency), float(tau), rmse, len(obs))
    return best


# --------------------------------------------------------------------------- #
# Perte de la maison k (nuit, poêle éteint depuis longtemps)
# --------------------------------------------------------------------------- #
def estimate_k(
    room: Sequence[float | None],
    t_out: Sequence[float | None],
    quiet: Sequence[bool],
    *,
    step: int = 30,
    min_segment: int = 150,
) -> tuple[float, int] | None:
    """Estime k par moindres carrés sur des écarts de ``step`` minutes.

    ``quiet[i]`` est vrai quand la minute i est « calme » : poêle éteint depuis
    longtemps et nuit. Renvoie (k, nombre de paires) ou None.
    """
    sxy = 0.0
    sxx = 0.0
    pairs = 0
    n = len(room)
    i = 0
    while i < n:
        if not quiet[i]:
            i += 1
            continue
        j = i
        while j < n and quiet[j]:
            j += 1
        if j - i >= min_segment:
            for s in range(i, j - step, step):
                t1, t2 = room[s], room[s + step]
                if t1 is None or t2 is None:
                    continue
                devs = [
                    room[m] - t_out[m]
                    for m in range(s, s + step + 1)
                    if room[m] is not None and t_out[m] is not None
                ]
                if not devs:
                    continue
                x = sum(devs) / len(devs)
                y = (t2 - t1) / (step / 60.0)
                sxy += x * y
                sxx += x * x
                pairs += 1
        i = j
    if pairs < 3 or sxx <= 0:
        return None
    k = -sxy / sxx
    if not MIN_K <= k <= MAX_K:
        return None
    return k, pairs


def ema(old: float, new: float, n: int, alpha: float = 0.3) -> float:
    """Moyenne glissante exponentielle ; la première mesure pèse davantage."""
    a = 0.6 if n == 0 else alpha
    return old + a * (new - old)


# --------------------------------------------------------------------------- #
# Estimation de la durée de chauffe avec le modèle appris
# --------------------------------------------------------------------------- #
def minutes_to_reach(
    t_room: float,
    target: float,
    t_out: float,
    model: Model,
    power_pct: float,
    *,
    max_minutes: int = 480,
) -> int:
    """Minutes nécessaires, poêle allumé maintenant à ``power_pct``, pour atteindre ``target``."""
    if t_room >= target:
        return 0
    u = max(0.0, min(100.0, power_pct)) / 100.0
    gain = model.a100 * u
    if model.k > 0 and t_out + gain / model.k <= target:
        return max_minutes
    latency = int(round(model.latency))
    t = t_room
    x = 0.0
    for minute in range(1, max_minutes + 1):
        d = u if minute - 1 >= latency else 0.0
        if model.tau > 1:
            x += (d - x) / model.tau
        else:
            x = d
        t += (model.a100 * x - model.k * (t - t_out)) / 60.0
        if t >= target:
            return minute
    return max_minutes
