"""Constantes de l'intégration Poêle adaptatif."""
from __future__ import annotations

DOMAIN = "poele_adaptatif"

PLATFORMS = [
    "calendar",
    "number",
    "select",
    "switch",
    "button",
    "sensor",
    "binary_sensor",
]

STORAGE_VERSION = 1

# --- Entités du poêle (intégration Rika Firenet) -------------------------------
CONF_CLIMATE = "climate_entity"
CONF_ON_OFF = "on_off_switch"
CONF_HEATING_TIMES = "heating_times_switch"
CONF_POWER = "power_number"
CONF_STATUS = "status_sensor"
CONF_PELLETS = "pellets_sensor"
CONF_ROOM_TEMP = "room_temperature_sensor"
CONF_MAIN_STATE = "main_state_sensor"
CONF_FAN = "fan_sensor"
CONF_DIAG = "feed_sensor"
CONF_FAN = "fan_sensor"
CONF_DIAG = "feed_sensor"
CONF_OUTDOOR_TEMP = "outdoor_temperature_sensor"

DEFAULT_ENTITIES = {
    CONF_CLIMATE: "climate.rika_firenet_le_poele",
    CONF_ON_OFF: "switch.salon_le_poele_on_off",
    CONF_HEATING_TIMES: "switch.salon_le_poele_heating_times",
    CONF_POWER: "number.salon_le_poele_heating_power",
    CONF_STATUS: "sensor.salon_le_poele_le_poele_stove_status",
    CONF_PELLETS: "sensor.salon_le_poele_le_poele_pellets_before_service",
    CONF_ROOM_TEMP: "sensor.station_meteo_temperature",
    CONF_MAIN_STATE: "sensor.salon_le_poele_le_poele_main_state",
    CONF_FAN: "sensor.salon_le_poele_le_poele_fan_velocity",
    CONF_DIAG: "sensor.salon_le_poele_le_poele_diag_motor",
    CONF_FAN: "sensor.salon_le_poele_le_poele_fan_velocity",
    CONF_DIAG: "sensor.salon_le_poele_le_poele_diag_motor",
    # Paramètres appris par les capteurs d'apprentissage de Home Assistant
    CONF_OUTDOOR_TEMP: "sensor.station_meteo_module_exterieur_temperature",
}

# --- Réglages de l'intégration -------------------------------------------------
SET_CONSIGNE = "consigne"
SET_HYSTERESIS = "hysteresis"
SET_ANTICIPATION_MODE = "anticipation_mode"
SET_ANTICIPATION_MIN = "anticipation_minutes"
SET_MIN_RUN = "min_run_minutes"
SET_COOLDOWN = "cooldown_minutes"
SET_PILOTAGE = "pilotage"
SET_LATENCY = "latency_minutes"  # supprimé en 0.3 (appris), conservé pour le nettoyage
SET_POWER_PLAN = "planned_power_pct"
SET_ADVANCE_MAX = "advance_max_minutes"

ANTICIPATION_OFF = "off"
ANTICIPATION_FIXED = "fixed"
ANTICIPATION_LEARNED = "learned"

DEFAULT_SETTINGS = {
    SET_CONSIGNE: 20.0,
    SET_HYSTERESIS: 0.5,
    SET_ANTICIPATION_MODE: ANTICIPATION_OFF,
    SET_ANTICIPATION_MIN: 90,
    SET_MIN_RUN: 60,
    SET_COOLDOWN: 30,
    SET_LATENCY: 20,
    SET_POWER_PLAN: 0,  # 0 = puissance habituelle apprise
    SET_ADVANCE_MAX: 180,
    # Sécurité : aucune commande automatique tant que ce réglage n'est pas activé.
    SET_PILOTAGE: False,
}

# Bornes des commandes du poêle (identiques au dashboard actuel)
CLIMATE_MIN = 14
CLIMATE_MAX = 28
POWER_MIN = 30
POWER_MAX = 100
POWER_STEP = 5

MODE_CONFORT = "Confort"
MODE_AUTO = "Auto"
MODE_MANUEL = "Manuel"
MODES = [MODE_CONFORT, MODE_AUTO, MODE_MANUEL]

# Délai minimal entre deux commandes automatiques (le cloud Rika est lent)
COMMAND_LOCK_MINUTES = 5

# Valeurs de départ du modèle, avant la première chauffe apprise
SEED_K = 0.02  # perte de la maison (1/h)
SEED_RISE_100 = 1.6  # montée brute à 100 % de puissance (°C/h)
SEED_LATENCY = 15.0  # minutes avant que le salon réagisse
SEED_TAU = 20.0  # minutes d'inertie de la montée
SEED_POWER = 92.0  # puissance relative habituelle en Confort (%)
FALLBACK_OUTDOOR = 5.0  # température extérieure si la sonde est indisponible (°C)

LEARNING_MIN_BURN_MINUTES = 45  # chauffe trop courte pour être apprise en dessous
LEARNING_LEAD_MINUTES = 90  # repos avant l'allumage pris en compte
LEARNING_TAIL_MINUTES = 60  # après l'arrêt : chaleur résiduelle
LEARNING_MAX_RMSE = 0.25  # °C : écart maximal toléré entre modèle et mesure
K_UPDATE_HOURS = 6
SAMPLE_KEEP_MINUTES = 72 * 60

# États principaux du poêle Rika : 1 arrêt/veille, 2-3 allumage, 4 marche,
# 5 nettoyage, 6 extinction. Le poêle « brûle » dans les états 2 à 5.
BURNING_STATES = {"2", "3", "4", "5"}
PENDING_START_MINUTES = 30
