"""Apprentissage intégré : échantillons -> ajustement après chaque chauffe -> paramètres."""
import random
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.poele_adaptatif import learner as lr
from custom_components.poele_adaptatif.const import DEFAULT_ENTITIES, DOMAIN
from custom_components.poele_adaptatif.learning import LearningManager


def _quant(v):
    return round(v / 0.1) * 0.1


def _fill(manager: LearningManager, start: datetime, power: list[float], t_out: float, truth: lr.Model, t0: float, night=True):
    """Remplit le gestionnaire avec une journée simulée (capteur 0,1 °C, MAJ toutes les 10 min)."""
    sim = lr.simulate(t0, [t_out] * len(power), power, truth)
    held = None
    for i, (p, v) in enumerate(zip(power, sim)):
        if i % 10 == 0:
            held = _quant(v)
        manager.record(start + timedelta(minutes=i), held, t_out, p, p > 0, night)


async def test_learns_from_a_run(hass: HomeAssistant, hass_storage) -> None:
    await hass.config.async_set_time_zone("Europe/Paris")
    truth = lr.Model(a100=2.0, k=0.02, latency=20, tau=25)
    manager = LearningManager(hass, "abc")
    start = dt_util.now().replace(hour=3, minute=0, second=0, microsecond=0) - timedelta(days=1)
    # 90 min de repos, 110 min de chauffe à 92 %, puis 120 min de repos
    power = [0.0] * 90 + [92.0] * 110 + [0.0] * 120
    _fill(manager, start, power, 3.0, truth, 18.2)
    run_start = start + timedelta(minutes=90)
    run_stop = start + timedelta(minutes=200)
    manager.on_run_end(run_start, run_stop)
    assert manager.n_runs == 0 and manager.model.a100 == 1.6
    changed = await manager.async_process(run_stop + timedelta(minutes=61))
    assert changed and manager.n_runs == 1
    # première mesure : forte pondération vers la valeur ajustée (départ 1,6 ; vérité 2,0)
    assert 1.8 < manager.model.a100 < 2.4, manager.data
    assert manager.data["last_fit"]["retenue"] is True
    assert 80 < manager.power < 100
    assert manager.data["pending"] == []


async def test_rejects_short_or_sparse_runs(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Paris")
    truth = lr.Model(a100=2.0, k=0.02, latency=20, tau=25)
    manager = LearningManager(hass, "abc")
    start = dt_util.now().replace(hour=3, minute=0, second=0, microsecond=0) - timedelta(days=1)
    power = [0.0] * 90 + [92.0] * 20 + [0.0] * 120   # chauffe de 20 min seulement
    _fill(manager, start, power, 3.0, truth, 18.2)
    manager.on_run_end(start + timedelta(minutes=90), start + timedelta(minutes=110))
    await manager.async_process(start + timedelta(minutes=300))
    assert manager.n_runs == 0
    assert manager.data["last_fit"]["retenue"] is False
    assert "courte" in manager.data["last_fit"]["raison"]


async def test_learns_k_from_cold_nights(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Paris")
    k_true = 0.015
    truth = lr.Model(a100=0, k=k_true, latency=0, tau=0)
    manager = LearningManager(hass, "abc")
    now = dt_util.now()
    start = now - timedelta(hours=10)
    n = 600
    _fill(manager, start, [0.0] * n, 2.0, truth, 20.4, night=True)
    changed = await manager.async_process(start + timedelta(minutes=n))
    assert changed
    assert manager.data["n_k"] == 1
    # k de départ 0,02 ; vérité 0,015 ; première mesure pondérée à 60 %
    assert 0.014 < manager.model.k < 0.019, manager.model


async def test_second_run_moves_gently(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Paris")
    truth = lr.Model(a100=2.0, k=0.02, latency=20, tau=25)
    manager = LearningManager(hass, "abc")
    manager.data["n_runs"] = 3
    manager.data["model"]["a100"] = 1.8
    start = dt_util.now().replace(hour=3, minute=0, second=0, microsecond=0) - timedelta(days=1)
    power = [0.0] * 90 + [92.0] * 110 + [0.0] * 120
    _fill(manager, start, power, 3.0, truth, 18.2)
    manager.on_run_end(start + timedelta(minutes=90), start + timedelta(minutes=200))
    await manager.async_process(start + timedelta(minutes=261))
    # après 3 chauffes la moyenne bouge d'environ 30 % de l'écart seulement
    assert 1.8 < manager.model.a100 < 2.0, manager.model


async def test_persistence_and_reset(hass: HomeAssistant, hass_storage) -> None:
    await hass.config.async_set_time_zone("Europe/Paris")
    manager = LearningManager(hass, "persist")
    manager.data["model"]["a100"] = 1.9
    manager.data["n_runs"] = 4
    manager.record(dt_util.now(), 19.5, 3.0, 0.0, False, True)
    manager._dirty = True
    manager._maybe_save(dt_util.now(), force=True)
    await hass.async_block_till_done()
    await manager._store.async_save(manager._payload())
    other = LearningManager(hass, "persist")
    await other.async_load()
    assert other.model.a100 == 1.9 and other.n_runs == 4 and len(other.samples) == 1
    await other.async_reset()
    assert other.model.a100 == 1.6 and other.n_runs == 0


async def test_integration_records_and_learns_end_to_end(hass: HomeAssistant, freezer) -> None:
    """Une vraie chauffe vue par l'intégration (états simulés minute par minute)."""
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    await hass.config.async_set_time_zone("Europe/Paris")
    truth = lr.Model(a100=1.9, k=0.02, latency=15, tau=20)
    t_out = 3.0
    power = [0.0] * 90 + [92.0] * 100 + [0.0] * 80
    sim = lr.simulate(18.3, [t_out] * len(power), power, truth)
    start = dt_util.parse_datetime("2026-11-23 03:30:00+01:00")
    freezer.move_to(start)
    hass.states.async_set("sensor.station_meteo_module_exterieur_temperature", str(t_out))
    hass.states.async_set("sensor.station_meteo_temperature", "18.3")
    hass.states.async_set("switch.salon_le_poele_on_off", "on")
    hass.states.async_set("switch.salon_le_poele_heating_times", "on")
    hass.states.async_set("sensor.salon_le_poele_le_poele_main_state", "1")
    hass.states.async_set("sensor.salon_le_poele_le_poele_fan_velocity", "1000")
    hass.states.async_set("sensor.salon_le_poele_le_poele_diag_motor", "0")
    hass.states.async_set("sensor.salon_le_poele_le_poele_stove_status", "standby")
    hass.states.async_set("climate.rika_firenet_le_poele", "auto", {"preset_mode": "comfort", "temperature": 20})
    entry = MockConfigEntry(domain=DOMAIN, data=dict(DEFAULT_ENTITIES))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    controller = hass.data[DOMAIN][entry.entry_id]

    held = 18.3
    total = len(power) + 70
    for i in range(total):
        now = start + timedelta(minutes=i)
        freezer.move_to(now)
        j = min(i, len(power) - 1)
        if i % 10 == 0:
            held = _quant(sim[j])
            hass.states.async_set("sensor.station_meteo_temperature", str(held))
        burning = 90 <= i < 190
        hass.states.async_set("sensor.salon_le_poele_le_poele_main_state", "4" if burning else "1")
        hass.states.async_set("sensor.salon_le_poele_le_poele_fan_velocity", "1268" if burning else "1000")
        async_fire_time_changed(hass, now)
        await hass.async_block_till_done()

    assert controller.learning.n_runs == 1, (controller.learning.data["pending"], controller.learning.data["last_fit"], len(controller.learning.samples))
    assert 1.6 < controller.learning.model.a100 < 2.5, controller.learning.model
    assert hass.states.get("sensor.poele_adaptatif_etat_de_l_apprentissage").state.startswith("En apprentissage")
    assert hass.states.get("sensor.poele_adaptatif_duree_de_chauffe_estimee").attributes["chauffes_apprises"] == 1
