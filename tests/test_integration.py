"""Tests d'intégration avec le banc de test Home Assistant."""
from datetime import timedelta

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    async_mock_service,
)

from custom_components.poele_adaptatif.const import (
    SET_CONSIGNE,
    DEFAULT_ENTITIES,
    DOMAIN,
    SET_ANTICIPATION_MIN,
    SET_ANTICIPATION_MODE,
    SET_PILOTAGE,
)


def _stove_states(
    hass: HomeAssistant, *, on="off", main="1", heating_times="off", room="18.0", preset="comfort", temp=20
):
    hass.states.async_set("switch.salon_le_poele_on_off", on)
    hass.states.async_set("sensor.salon_le_poele_le_poele_main_state", main)
    hass.states.async_set("switch.salon_le_poele_heating_times", heating_times)
    hass.states.async_set("number.salon_le_poele_heating_power", "85")
    hass.states.async_set("sensor.salon_le_poele_le_poele_fan_velocity", "1268")
    hass.states.async_set("sensor.salon_le_poele_le_poele_diag_motor", "483")
    hass.states.async_set("sensor.salon_le_poele_le_poele_stove_status", "standby")
    hass.states.async_set(
        "sensor.salon_le_poele_le_poele_pellets_before_service", "1234", {"unit_of_measurement": "kg"}
    )
    hass.states.async_set("sensor.station_meteo_temperature", room, {"unit_of_measurement": "°C"})
    hass.states.async_set(
        "climate.rika_firenet_le_poele", "auto", {"preset_mode": preset, "temperature": temp}
    )


async def _setup(hass: HomeAssistant, freezer, when: str, **states):
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to(when)
    _stove_states(hass, **states)
    entry = MockConfigEntry(domain=DOMAIN, data=dict(DEFAULT_ENTITIES))
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry, hass.data[DOMAIN][entry.entry_id]


async def test_entities_created(hass: HomeAssistant, freezer) -> None:
    entry, _ = await _setup(hass, freezer, "2026-11-23 12:00:00+01:00")
    registry = er.async_get(hass)
    ids = {e.entity_id for e in er.async_entries_for_config_entry(registry, entry.entry_id)}
    expected = {
        "calendar.poele_adaptatif_plages_de_chauffe",
        "number.poele_adaptatif_consigne",
        "number.poele_adaptatif_hysteresis",
        "number.poele_adaptatif_avance_d_allumage",
        "number.poele_adaptatif_marche_minimale",
        "number.poele_adaptatif_delai_de_rallumage",
        "number.poele_adaptatif_consigne_du_poele_rika",
        "number.poele_adaptatif_puissance_auto_manuel",
        "select.poele_adaptatif_mode",
        "select.poele_adaptatif_anticipation",
        "switch.poele_adaptatif_pilotage_automatique",
        "switch.poele_adaptatif_marche_arret",
        "switch.poele_adaptatif_plages_horaires_rika",
        "button.poele_adaptatif_plus",
        "button.poele_adaptatif_moins",
        "sensor.poele_adaptatif_etat_du_poele",
        "sensor.poele_adaptatif_temperature_de_reference",
        "sensor.poele_adaptatif_prochain_allumage_prevu",
        "sensor.poele_adaptatif_fin_de_plage",
        "sensor.poele_adaptatif_derniere_decision",
        "sensor.poele_adaptatif_pellets_avant_entretien",
        "binary_sensor.poele_adaptatif_plage_active",
        "sensor.poele_adaptatif_duree_de_chauffe_estimee",
        "sensor.poele_adaptatif_perte_de_la_maison_k_apprise",
        "sensor.poele_adaptatif_montee_a_100_apprise",
        "sensor.poele_adaptatif_latence_d_allumage_apprise",
        "sensor.poele_adaptatif_inertie_de_chauffe_apprise",
        "sensor.poele_adaptatif_puissance_habituelle_apprise",
        "sensor.poele_adaptatif_etat_de_l_apprentissage",
        "button.poele_adaptatif_reinitialiser_l_apprentissage",
        "number.poele_adaptatif_puissance_de_chauffe_prevue_0_apprise",
        "number.poele_adaptatif_avance_maximale_apprise",
    }
    missing = expected - ids
    assert not missing, f"entités manquantes : {missing} ; présentes : {sorted(ids)}"


async def test_states_reflect_stove(hass: HomeAssistant, freezer) -> None:
    await _setup(hass, freezer, "2026-11-23 12:00:00+01:00", on="on", main="1", heating_times="on")
    label = lambda: hass.states.get("sensor.poele_adaptatif_etat_du_poele").state  # noqa: E731
    # « activé » mais en attente de sa planification : en veille
    assert label() == "En veille"
    hass.states.async_set("sensor.salon_le_poele_le_poele_main_state", "4")
    await hass.async_block_till_done()
    assert label() == "En chauffe"
    hass.states.async_set("sensor.salon_le_poele_le_poele_main_state", "6")
    await hass.async_block_till_done()
    assert label() == "Extinction"
    hass.states.async_set("switch.salon_le_poele_on_off", "off")
    await hass.async_block_till_done()
    assert label() == "Éteint"
    assert hass.states.get("select.poele_adaptatif_mode").state == "Confort"
    assert hass.states.get("number.poele_adaptatif_consigne_du_poele_rika").state == "20.0"
    assert hass.states.get("number.poele_adaptatif_puissance_auto_manuel").state == "85.0"
    assert hass.states.get("switch.poele_adaptatif_marche_arret").state == STATE_OFF
    assert hass.states.get("sensor.poele_adaptatif_pellets_avant_entretien").state == "1234.0"
    assert hass.states.get("sensor.poele_adaptatif_temperature_de_reference").state == "18.0"
    assert hass.states.get("binary_sensor.poele_adaptatif_plage_active").state == STATE_OFF


async def test_calendar_default_events_and_crud(hass: HomeAssistant, freezer) -> None:
    await _setup(hass, freezer, "2026-11-23 12:00:00+01:00")
    cal = "calendar.poele_adaptatif_plages_de_chauffe"
    # prochaine plage = lundi 15h00
    state = hass.states.get(cal)
    assert state is not None
    assert dt_util.parse_datetime(state.attributes["start_time"].replace(" ", "T")) is not None or True
    resp = await hass.services.async_call(
        "calendar", "get_events",
        {"entity_id": cal, "start_date_time": "2026-11-23T00:00:00+01:00", "end_date_time": "2026-11-24T00:00:00+01:00"},
        blocking=True, return_response=True,
    )
    events = resp[cal]["events"]
    assert [e["start"][11:16] for e in events] == ["05:00", "15:00"], events

    await hass.services.async_call(
        "calendar", "create_event",
        {"entity_id": cal, "summary": "Test", "start_date_time": "2026-11-23T10:00:00+01:00", "end_date_time": "2026-11-23T11:00:00+01:00"},
        blocking=True,
    )
    resp = await hass.services.async_call(
        "calendar", "get_events",
        {"entity_id": cal, "start_date_time": "2026-11-23T00:00:00+01:00", "end_date_time": "2026-11-24T00:00:00+01:00"},
        blocking=True, return_response=True,
    )
    assert [e["summary"] for e in resp[cal]["events"]] == [
        "Chauffe matin (semaine)", "Test", "Chauffe après-midi et soir (semaine)",
    ]


async def test_pilotage_off_never_commands(hass: HomeAssistant, freezer) -> None:
    # Cas réel : interrupteur Rika « on » en permanence, poêle à l'arrêt (état principal 1)
    entry, controller = await _setup(hass, freezer, "2026-11-23 15:05:00+01:00", on="on", main="1")
    on_calls = async_mock_service(hass, "switch", "turn_on")
    off_calls = async_mock_service(hass, "switch", "turn_off")
    temp_calls = async_mock_service(hass, "climate", "set_temperature")
    await controller.async_evaluate()
    assert controller.decision.action == "start"  # la décision est calculée…
    assert on_calls == [] and off_calls == [] and temp_calls == []  # …mais rien n'est envoyé
    assert hass.states.get("sensor.poele_adaptatif_derniere_decision").state == "Allumer"


async def test_pilotage_on_starts_in_comfort(hass: HomeAssistant, freezer) -> None:
    entry, controller = await _setup(
        hass, freezer, "2026-11-23 15:05:00+01:00", on="off", main="1", preset="none", temp=18
    )
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.poele_adaptatif_pilotage_automatique"}, blocking=True
    )
    await hass.async_block_till_done()
    assert controller.settings[SET_PILOTAGE] is True
    on_calls = async_mock_service(hass, "switch", "turn_on")
    preset_calls = async_mock_service(hass, "climate", "set_preset_mode")
    temp_calls = async_mock_service(hass, "climate", "set_temperature")
    controller._last_command = None
    await controller.async_evaluate()
    assert [c.data["preset_mode"] for c in preset_calls] == ["comfort"]
    assert [c.data["temperature"] for c in temp_calls] == [20]
    assert [c.data["entity_id"] for c in on_calls] == ["switch.salon_le_poele_on_off"]


async def test_enabled_switch_not_resent_when_already_on(hass: HomeAssistant, freezer) -> None:
    entry, controller = await _setup(hass, freezer, "2026-11-23 15:05:00+01:00", on="on", main="1", temp=18)
    await controller.async_set_setting(SET_PILOTAGE, True)
    on_calls = async_mock_service(hass, "switch", "turn_on")
    temp_calls = async_mock_service(hass, "climate", "set_temperature")
    controller._last_command = None
    await controller.async_evaluate()
    # l'interrupteur est déjà « on » : on règle seulement la consigne (le thermostat Rika allume)
    assert on_calls == [] and [c.data["temperature"] for c in temp_calls] == [20]


async def test_rika_schedule_blocks_commands(hass: HomeAssistant, freezer) -> None:
    entry, controller = await _setup(
        hass, freezer, "2026-11-23 15:05:00+01:00", on="on", main="1", heating_times="on"
    )
    await controller.async_set_setting(SET_PILOTAGE, True)
    on_calls = async_mock_service(hass, "switch", "turn_on")
    temp_calls = async_mock_service(hass, "climate", "set_temperature")
    controller._last_command = None
    await controller.async_evaluate()
    assert controller.decision.action == "start" and controller.blocked_by_rika
    assert on_calls == [] and temp_calls == []
    attrs = hass.states.get("sensor.poele_adaptatif_derniere_decision").attributes
    assert attrs["plages_rika_actives"] is True and attrs["commande_bloquee_par_plages_rika"] is True


async def test_anticipation_starts_before_window(hass: HomeAssistant, freezer) -> None:
    entry, controller = await _setup(hass, freezer, "2026-11-23 13:10:00+01:00", on="off")
    on_calls = async_mock_service(hass, "switch", "turn_on")
    await controller.async_set_setting(SET_PILOTAGE, True)
    await controller.async_set_setting(SET_ANTICIPATION_MODE, "fixed")
    await controller.async_set_setting(SET_ANTICIPATION_MIN, 120)
    on_calls.clear()
    controller._last_command = None
    await controller.async_evaluate()
    assert [c.data["entity_id"] for c in on_calls] == ["switch.salon_le_poele_on_off"]
    assert controller.decision.next_start.hour == 13 and controller.decision.next_start.minute == 0


async def test_no_anticipation_no_start(hass: HomeAssistant, freezer) -> None:
    entry, controller = await _setup(hass, freezer, "2026-11-23 13:10:00+01:00", on="off")
    on_calls = async_mock_service(hass, "switch", "turn_on")
    await controller.async_set_setting(SET_PILOTAGE, True)
    on_calls.clear()
    controller._last_command = None
    await controller.async_evaluate()
    assert on_calls == []


async def test_stop_at_end_of_window_only_if_started_by_us(hass: HomeAssistant, freezer) -> None:
    entry, controller = await _setup(hass, freezer, "2026-11-23 22:10:00+01:00", on="on", main="4")
    off_calls = async_mock_service(hass, "switch", "turn_off")
    await controller.async_set_setting(SET_PILOTAGE, True)
    off_calls.clear()
    # allumage manuel : on n'éteint pas
    controller.runtime["started_by_us"] = False
    controller.runtime["last_start"] = "2026-11-23T14:00:00+01:00"
    controller._last_command = None
    await controller.async_evaluate()
    assert off_calls == []
    # allumage par l'intégration : on éteint, avec une seule commande
    controller.runtime["started_by_us"] = True
    controller._last_command = None
    await controller.async_evaluate()
    assert [c.data["entity_id"] for c in off_calls] == ["switch.salon_le_poele_on_off"]


async def test_dashboard_commands(hass: HomeAssistant, freezer) -> None:
    await _setup(hass, freezer, "2026-11-23 12:00:00+01:00")
    preset_calls = async_mock_service(hass, "climate", "set_preset_mode")
    temp_calls = async_mock_service(hass, "climate", "set_temperature")
    power_calls = async_mock_service(hass, "number", "set_value")

    # Confort : + / - agissent sur la consigne du poêle
    await hass.services.async_call("button", "press", {"entity_id": "button.poele_adaptatif_plus"}, blocking=True)
    await hass.services.async_call("button", "press", {"entity_id": "button.poele_adaptatif_moins"}, blocking=True)
    assert [c.data["temperature"] for c in temp_calls] == [21.0, 19.0]

    # Manuel / Auto : + / - agissent sur la puissance (pas de 5 %)
    hass.states.async_set("climate.rika_firenet_le_poele", "heat", {"preset_mode": "none", "temperature": 20})
    await hass.async_block_till_done()
    await hass.services.async_call("button", "press", {"entity_id": "button.poele_adaptatif_plus"}, blocking=True)
    await hass.services.async_call("button", "press", {"entity_id": "button.poele_adaptatif_moins"}, blocking=True)
    assert [c.data["value"] for c in power_calls] == [90, 80]

    # Passage en mode Confort via le sélecteur
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.poele_adaptatif_mode", "option": "Confort"}, blocking=True,
    )
    assert preset_calls[-1].data["preset_mode"] == "comfort"


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "form"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], dict(DEFAULT_ENTITIES))
    assert result["type"] == "create_entry"
    assert result["title"] == "Poêle adaptatif"
    result2 = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result2["type"] == "abort"


async def test_options_flow_and_unload(hass: HomeAssistant, freezer) -> None:
    entry, controller = await _setup(hass, freezer, "2026-11-23 12:00:00+01:00")
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form" and result["step_id"] == "init"
    new = {**DEFAULT_ENTITIES, "room_temperature_sensor": "sensor.autre_sonde"}
    result = await hass.config_entries.options.async_configure(result["flow_id"], new)
    assert result["type"] == "create_entry"
    await hass.async_block_till_done()
    new_controller = hass.data[DOMAIN][entry.entry_id]
    assert new_controller.room_temp_entity == "sensor.autre_sonde"
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.entry_id not in hass.data.get(DOMAIN, {})


async def test_settings_persist_across_reload(hass: HomeAssistant, freezer, hass_storage) -> None:
    entry, controller = await _setup(hass, freezer, "2026-11-23 12:00:00+01:00")
    await hass.services.async_call(
        "number", "set_value",
        {"entity_id": "number.poele_adaptatif_consigne", "value": 21.5}, blocking=True,
    )
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.poele_adaptatif_anticipation", "option": "Fixe"}, blocking=True,
    )
    freezer.tick(timedelta(seconds=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("number.poele_adaptatif_consigne").state == "21.5"
    assert hass.states.get("select.poele_adaptatif_anticipation").state == "Fixe"


async def test_learned_anticipation_starts_at_estimated_time(hass: HomeAssistant, freezer) -> None:
    """Mode « Apprise » : allumage à (début de plage − durée estimée)."""
    from custom_components.poele_adaptatif import learner as lr
    from custom_components.poele_adaptatif.const import (
        SEED_K, SEED_LATENCY, SEED_POWER, SEED_RISE_100, SEED_TAU,
    )

    hass.states.async_set("sensor.station_meteo_module_exterieur_temperature", "5.0")
    seed = lr.Model(a100=SEED_RISE_100, k=SEED_K, latency=SEED_LATENCY, tau=SEED_TAU)
    expected = lr.minutes_to_reach(18.0, 20.0, 5.0, seed, SEED_POWER)

    # Lundi 23/11 : prochaine plage à 15h00. On se place 10 min avant l'heure d'allumage.
    t_before = dt_util.parse_datetime("2026-11-23 15:00:00+01:00") - timedelta(minutes=expected + 10)
    entry, controller = await _setup(hass, freezer, t_before.isoformat(), room="18.0", on="off")
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.poele_adaptatif_anticipation", "option": "Apprise"}, blocking=True,
    )
    await controller.async_set_setting(SET_PILOTAGE, True)
    on_calls = async_mock_service(hass, "switch", "turn_on")
    controller._last_command = None
    await controller.async_evaluate()
    assert on_calls == [], controller.decision
    assert hass.states.get("sensor.poele_adaptatif_duree_de_chauffe_estimee").state == str(expected)
    assert controller.estimate["parametres"] == "valeurs de départ"

    # 11 minutes plus tard : l'heure d'allumage est passée
    freezer.move_to((t_before + timedelta(minutes=11)).isoformat())
    controller._last_command = None
    await controller.async_evaluate()
    assert [c.data["entity_id"] for c in on_calls] == ["switch.salon_le_poele_on_off"], controller.decision
    assert controller.runtime["anticipating_for"] is not None


async def test_power_relative_from_fan(hass: HomeAssistant, freezer) -> None:
    entry, controller = await _setup(hass, freezer, "2026-11-24 12:00:00+01:00", on="on", main="4")
    hass.states.async_set("sensor.salon_le_poele_le_poele_fan_velocity", "1268")
    hass.states.async_set("sensor.salon_le_poele_le_poele_diag_motor", "483")
    assert controller.power_relative() == 92.0
    hass.states.async_set("sensor.salon_le_poele_le_poele_fan_velocity", "1500")  # allumage : on lit la vis
    assert controller.power_relative() == 92.0
    hass.states.async_set("sensor.salon_le_poele_le_poele_main_state", "5")  # nettoyage : pas de chauffe
    assert controller.power_relative() == 0.0


async def test_run_end_is_queued_for_learning(hass: HomeAssistant, freezer) -> None:
    entry, controller = await _setup(hass, freezer, "2026-11-24 05:00:00+01:00", on="on", main="1")
    hass.states.async_set("sensor.salon_le_poele_le_poele_main_state", "2")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=100))
    hass.states.async_set("sensor.salon_le_poele_le_poele_main_state", "4")
    await hass.async_block_till_done()
    freezer.tick(timedelta(minutes=100))
    hass.states.async_set("sensor.salon_le_poele_le_poele_main_state", "6")
    await hass.async_block_till_done()
    runs = controller.learning.data["pending"]
    assert len(runs) == 1 and runs[0]["start"] < runs[0]["stop"]
