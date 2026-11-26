"""Apprentissage automatique du salon : perte k, montée, latence, inertie, puissance.

À chaque minute, un échantillon (température du salon, extérieur, puissance relative,
poêle allumé, nuit) est mémorisé. Une heure après chaque arrêt du poêle, la chauffe est
ajustée sur le modèle (voir learner.py) et les paramètres appris sont mis à jour par
moyenne glissante. La perte de la maison k est réestimée toutes les 6 heures sur les
périodes calmes de nuit. Rien n'est à corriger à la main : un bouton permet seulement de
repartir des valeurs de départ.
"""
from __future__ import annotations

import copy
import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from . import bootstrap as bs
from . import learner as lr
from .const import (
    DOMAIN,
    FALLBACK_OUTDOOR,
    K_UPDATE_HOURS,
    LEARNING_LEAD_MINUTES,
    LEARNING_MAX_RMSE,
    LEARNING_MIN_BURN_MINUTES,
    LEARNING_TAIL_MINUTES,
    SAMPLE_KEEP_MINUTES,
    SEED_K,
    SEED_LATENCY,
    SEED_POWER,
    SEED_RISE_100,
    SEED_TAU,
    STORAGE_VERSION,
)

_LOGGER = logging.getLogger(__name__)

PROCESS_EVERY = timedelta(minutes=5)
SAVE_EVERY = timedelta(minutes=30)


def _default_data() -> dict[str, Any]:
    return {
        "model": {"a100": SEED_RISE_100, "k": SEED_K, "latency": SEED_LATENCY, "tau": SEED_TAU},
        "power": SEED_POWER,
        "n_runs": 0,
        "n_k": 0,
        "k_pairs": 0,
        "k_updated": None,
        "pending": [],
        "last_fit": None,
        "history": [],
        "bootstrapped": None,
        "done_starts": [],
    }


class LearningManager:
    """Échantillons, ajustements et paramètres appris (persistés)."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._hass = hass
        self._store: Store = Store(hass, STORAGE_VERSION, f"{DOMAIN}.learning.{entry_id}")
        self.samples: list[list[Any]] = []
        self.data: dict[str, Any] = _default_data()
        self._dirty = False
        self._last_save: datetime | None = None
        self._last_sample = 0.0
        self._last_process: datetime | None = None
        self._busy = False
        self._h = ("", "", "", "", "")

    # ------------------------------------------------------------------ #
    # Accès aux paramètres appris
    # ------------------------------------------------------------------ #
    @property
    def model(self) -> lr.Model:
        m = self.data["model"]
        return lr.Model(a100=m["a100"], k=m["k"], latency=m["latency"], tau=m["tau"])

    @property
    def power(self) -> float:
        return float(self.data["power"])

    @property
    def n_runs(self) -> int:
        return int(self.data["n_runs"])

    @property
    def n_k(self) -> int:
        return int(self.data["n_k"])

    @property
    def confidence(self) -> str:
        if self.n_runs == 0:
            return "valeurs de départ"
        return f"apprises sur {self.n_runs} chauffe{'s' if self.n_runs > 1 else ''}"

    # ------------------------------------------------------------------ #
    # Persistance
    # ------------------------------------------------------------------ #
    def _payload(self) -> dict[str, Any]:
        return {"data": self.data, "samples": self.samples}

    async def async_load(self) -> None:
        stored = await self._store.async_load()
        if not stored:
            return
        data = _default_data()
        data.update({k: v for k, v in stored.get("data", {}).items() if k in data})
        data["model"] = {**_default_data()["model"], **data["model"]}
        self.data = data
        self.samples = [list(s) for s in stored.get("samples", [])]

    def _maybe_save(self, now: datetime, force: bool = False) -> None:
        if not self._dirty:
            return
        if not force and self._last_save is not None and now - self._last_save < SAVE_EVERY:
            return
        self._dirty = False
        self._last_save = now
        self._hass.async_create_task(self._store.async_save(self._payload()))

    async def async_reset(self) -> None:
        """Repart des valeurs de départ (les échantillons sont conservés)."""
        self.data = _default_data()
        self.data["last_fit"] = {"retenue": False, "raison": "apprentissage réinitialisé"}
        await self._store.async_save(self._payload())

    # ------------------------------------------------------------------ #
    # Échantillons (une fois par minute) et fin de chauffe
    # ------------------------------------------------------------------ #
    def record(
        self,
        now: datetime,
        room: float | None,
        t_out: float | None,
        power: float,
        burning: bool,
        night: bool,
    ) -> None:
        ts = now.timestamp()
        if ts - self._last_sample < 55:
            return
        self._last_sample = ts
        self.samples.append(
            [int(ts), room, t_out, round(float(power or 0.0), 1), 1 if burning else 0, 1 if night else 0]
        )
        extra = len(self.samples) - SAMPLE_KEEP_MINUTES
        if extra > 0:
            del self.samples[:extra]
        self._dirty = True

    def on_run_end(self, start: datetime | None, stop: datetime) -> None:
        """Une chauffe vient de s'arrêter : elle sera ajustée une heure plus tard."""
        if start is None or stop <= start:
            return
        pending = self.data["pending"]
        pending.append({"start": start.isoformat(), "stop": stop.isoformat()})
        del pending[:-10]
        self._dirty = True

    # ------------------------------------------------------------------ #
    # Grille d'une minute à partir des échantillons
    # ------------------------------------------------------------------ #
    def _grid(self, t0: int, t1: int) -> dict[str, list]:
        n = int((t1 - t0) // 60) + 1
        room: list[float | None] = [None] * n
        out: list[float | None] = [None] * n
        power = [0.0] * n
        burning = [0] * n
        night = [0] * n
        have = [False] * n
        for ts, r, o, p, b, ni in self.samples:
            i = int((ts - t0) // 60)
            if 0 <= i < n:
                room[i], out[i], power[i] = r, o, float(p or 0.0)
                burning[i], night[i], have[i] = int(b), int(ni), True
        # report de la dernière valeur connue pour les petits trous (≤ 15 min)
        last_r = last_o = None
        gap = 0
        for i in range(n):
            if have[i]:
                gap = 0
                last_r = room[i] if room[i] is not None else last_r
                last_o = out[i] if out[i] is not None else last_o
                if out[i] is None:
                    out[i] = last_o
            else:
                gap += 1
                if gap <= 15:
                    room[i], out[i] = last_r, last_o
        return {"room": room, "out": out, "power": power, "burning": burning,
                "night": night, "have": have, "n": n}

    # ------------------------------------------------------------------ #
    # Traitement périodique
    # ------------------------------------------------------------------ #
    async def async_process(self, now: datetime) -> bool:
        """Ajuste les chauffes terminées et réestime k. Renvoie True si quelque chose a changé."""
        if self._busy:
            return False
        if self._last_process is not None and now - self._last_process < PROCESS_EVERY:
            return False
        self._busy = True
        self._last_process = now
        changed = False
        try:
            changed = await self._learn_runs(now) or changed
            changed = await self._learn_k(now) or changed
            self._maybe_save(now, force=changed)
        except Exception:  # noqa: BLE001 - l'apprentissage ne doit jamais bloquer la régulation
            _LOGGER.exception("Erreur pendant l'apprentissage")
        finally:
            self._busy = False
        return changed

    async def _learn_runs(self, now: datetime) -> bool:
        changed = False
        keep: list[dict[str, str]] = []
        for run in list(self.data["pending"]):
            try:
                start = dt_util.as_local(datetime.fromisoformat(run["start"]))
                stop = dt_util.as_local(datetime.fromisoformat(run["stop"]))
            except (KeyError, ValueError):
                continue
            if now < stop + timedelta(minutes=LEARNING_TAIL_MINUTES):
                keep.append(run)  # la chaleur résiduelle n'est pas finie
                continue
            if now - stop > timedelta(hours=66):
                continue  # trop ancien : les échantillons ont disparu
            await self._learn_one(start, stop)
            changed = True
        self.data["pending"] = keep
        return changed

    def _mark_done(self, start: datetime) -> None:
        done = self.data["done_starts"]
        done.append(int(start.timestamp()))
        del done[:-30]

    def _reject(self, start: datetime, burn_min: float, reason: str, **extra: Any) -> None:
        self.data["last_fit"] = {
            "debut": start.isoformat(timespec="minutes"),
            "duree_min": round(burn_min),
            "retenue": False,
            "raison": reason,
            **extra,
        }
        self._mark_done(start)
        self._dirty = True

    async def _learn_one(self, start: datetime, stop: datetime) -> None:
        burn_min = (stop - start).total_seconds() / 60
        if burn_min < LEARNING_MIN_BURN_MINUTES:
            self._reject(start, burn_min, f"chauffe trop courte ({burn_min:.0f} min)")
            return
        t0 = int((start - timedelta(minutes=LEARNING_LEAD_MINUTES)).timestamp())
        t1 = int((stop + timedelta(minutes=LEARNING_TAIL_MINUTES)).timestamp())
        g = self._grid(t0, t1)
        coverage = sum(g["have"]) / g["n"]
        if coverage < 0.85:
            self._reject(start, burn_min, f"données incomplètes ({coverage:.0%})")
            return
        if any(g["burning"][: LEARNING_LEAD_MINUTES - 10]):
            self._reject(start, burn_min, "poêle déjà chaud avant l'allumage")
            return
        out = [o if o is not None else FALLBACK_OUTDOOR for o in g["out"]]
        fit = await self._hass.async_add_executor_job(
            lr.fit_run, g["room"], out, g["power"], self.data["model"]["k"]
        )
        if fit is None:
            self._reject(start, burn_min, "ajustement impossible")
            return
        if fit.rmse > LEARNING_MAX_RMSE:
            self._reject(start, burn_min, f"écart trop grand ({fit.rmse:.2f} °C)", ecart=round(fit.rmse, 3))
            return
        if fit.a100 <= lr.MIN_A + 0.01 or fit.a100 >= lr.MAX_A - 0.01:
            self._reject(start, burn_min, "montée hors limites", montee=round(fit.a100, 2))
            return
        n = self.n_runs
        model = self.data["model"]
        model["a100"] = lr.ema(model["a100"], fit.a100, n)
        model["latency"] = lr.ema(model["latency"], fit.latency, n)
        model["tau"] = lr.ema(model["tau"], fit.tau, n)
        burning_power = [p for p, b in zip(g["power"], g["burning"]) if b and p > 0]
        if burning_power:
            self.data["power"] = lr.ema(self.data["power"], sum(burning_power) / len(burning_power), n)
        self.data["n_runs"] = n + 1
        self._mark_done(start)
        record = {
            "debut": start.isoformat(timespec="minutes"),
            "duree_min": round(burn_min),
            "retenue": True,
            "raison": "ajustement retenu",
            "montee": round(fit.a100, 2),
            "latence": fit.latency,
            "inertie": fit.tau,
            "ecart": round(fit.rmse, 3),
        }
        self.data["last_fit"] = record
        self.data["history"] = (self.data["history"] + [record])[-10:]
        self._dirty = True
        _LOGGER.info("Apprentissage : chauffe du %s retenue -> %s", start.isoformat(timespec="minutes"), model)

    async def _learn_k(self, now: datetime) -> bool:
        if self.data["k_updated"]:
            try:
                last = dt_util.as_local(datetime.fromisoformat(self.data["k_updated"]))
                if now - last < timedelta(hours=K_UPDATE_HOURS):
                    return False
            except ValueError:
                pass
        t1 = int(now.timestamp())
        t0 = t1 - 48 * 3600
        g = self._grid(t0, t1)
        quiet = [False] * g["n"]
        since_burn = 0
        seen_start = False
        for i in range(g["n"]):
            if g["burning"][i] or not g["have"][i]:
                since_burn = 0
            else:
                since_burn += 1
            seen_start = seen_start or g["have"][i]
            quiet[i] = bool(
                seen_start and since_burn >= 90 and g["night"][i]
                and g["have"][i] and g["room"][i] is not None
            )
        est = await self._hass.async_add_executor_job(lr.estimate_k, g["room"], g["out"], quiet)
        if est is None:
            return False
        k_new, pairs = est
        model = self.data["model"]
        model["k"] = lr.ema(model["k"], k_new, self.n_k)
        self.data["n_k"] = self.n_k + 1
        self.data["k_pairs"] = pairs
        self.data["k_updated"] = now.isoformat(timespec="minutes")
        self._dirty = True
        _LOGGER.info("Apprentissage : k = %.4f (mesure %.4f sur %d paires)", model["k"], k_new, pairs)
        return True

    # ------------------------------------------------------------------ #
    # Amorçage depuis l'historique du recorder
    # ------------------------------------------------------------------ #
    def configure_history(self, room: str, outdoor: str, main: str, fan: str, feed: str) -> None:
        self._h = (room, outdoor, main, fan, feed)

    def _history_entities(self) -> list[str]:
        return [*self._h, "sun.sun"]

    async def _fetch_history(self, start: datetime, end: datetime) -> bs.Series:
        """Changements d'état du recorder, sous la forme {entité: [(timestamp, état)]}."""
        from homeassistant.components.recorder import get_instance
        from homeassistant.components.recorder import history

        instance = get_instance(self._hass)
        await instance.async_db_ready
        entities = self._history_entities()

        def _query() -> dict[str, list]:
            return history.get_significant_states(
                self._hass, start, end, entities,
                include_start_time_state=True, significant_changes_only=False,
                minimal_response=False, no_attributes=True,
            )

        raw = await instance.async_add_executor_job(_query)
        out: bs.Series = {}
        for entity_id, states in raw.items():
            pts = []
            for st in states:
                when = st.last_changed if st.last_changed else st.last_updated
                pts.append((when.timestamp(), st.state))
            out[entity_id] = pts
        return out

    async def async_bootstrap(self, now: datetime, hours: int = 70) -> dict[str, Any]:
        """Apprend sur les chauffes déjà passées (une seule fois au démarrage, ou à la demande)."""
        report: dict[str, Any] = {"echantillons": 0, "chauffes": 0}
        try:
            end = now
            start = now - timedelta(hours=hours)
            series = await self._fetch_history(start, end)
            room, outdoor, main, fan, feed = self._h
            built = bs.build_samples(series, room, outdoor, main, fan, feed, start.timestamp(), end.timestamp())
            have = {s[0] // 60 for s in self.samples}
            added = [s for s in built if s[0] // 60 not in have]
            self.samples = sorted(self.samples + added, key=lambda s: s[0])[-SAMPLE_KEEP_MINUTES:]
            report["echantillons"] = len(added)
            done = set(self.data["done_starts"])
            queued = {r["start"] for r in self.data["pending"]}
            for a, b in bs.runs_from_samples(built):
                if any(abs(a - d) < 600 for d in done):
                    continue
                start_dt = dt_util.as_local(datetime.fromtimestamp(a, dt_util.UTC))
                stop_dt = dt_util.as_local(datetime.fromtimestamp(b, dt_util.UTC))
                if start_dt.isoformat() in queued:
                    continue
                self.data["pending"].append({"start": start_dt.isoformat(), "stop": stop_dt.isoformat()})
                report["chauffes"] += 1
            self.data["pending"].sort(key=lambda r: r["start"])
            del self.data["pending"][:-10]
            self.data["bootstrapped"] = now.isoformat(timespec="minutes")
            self._dirty = True
            self._last_process = None
            await self.async_process(now)
            self._maybe_save(now, force=True)
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Amorçage sur l'historique impossible")
            report["erreur"] = True
        return report
