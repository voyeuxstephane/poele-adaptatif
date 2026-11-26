"""Amorçage de l'apprentissage depuis l'historique."""
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.poele_adaptatif import bootstrap as bs
from custom_components.poele_adaptatif import learner as lr
from custom_components.poele_adaptatif.learning import LearningManager

R, O, M, F, D = "room", "out", "main", "fan", "feed"


def test_power_from():
    assert bs.power_from("4", 1100.0, None) == round((1100 - 640) / 1.3 / 5.25, 1)
    assert bs.power_from("1", 1100.0, 300.0) == 0.0
    assert bs.power_from("4", 0.0, 262.5) == 50.0
    assert bs.power_from("4", None, None) == 0.0


def test_build_samples_and_runs():
    t0 = 1_700_000_000 // 60 * 60
    series = {
        R: [(t0 - 100, "18.0")],
        O: [(t0 - 100, "3.0")],
        M: [(t0 - 100, "1"), (t0 + 600, "2"), (t0 + 900, "4"), (t0 + 3600, "6"), (t0 + 3900, "1")],
        F: [(t0 - 100, "0"), (t0 + 900, "1200")],
        D: [(t0 - 100, "0")],
        "sun.sun": [(t0 - 100, "below_horizon")],
    }
    s = bs.build_samples(series, R, O, M, F, D, t0, t0 + 7200)
    assert len(s) == 121
    assert s[0][4] == 0 and s[11][4] == 1 and s[16][3] > 0 and s[0][5] == 1
    runs = bs.runs_from_samples(s)
    assert len(runs) == 1
    a, b = runs[0]
    assert a == t0 + 600 and b == t0 + 3600 + 5 * 60 - 0 or abs(b - (t0 + 3600)) <= 360


async def test_bootstrap_learns_past_run(hass: HomeAssistant, hass_storage) -> None:
    await hass.config.async_set_time_zone("Europe/Paris")
    truth = lr.Model(a100=2.0, k=0.02, latency=20, tau=25)
    now = dt_util.now().replace(second=0, microsecond=0)
    start = now - timedelta(hours=8)
    power = [0.0] * 90 + [92.0] * 110 + [0.0] * 120
    sim = lr.simulate(18.2, [3.0] * len(power), power, truth)
    ts = lambda i: (start + timedelta(minutes=i)).timestamp()  # noqa: E731
    room, main, fan = [], [], []
    for i, v in enumerate(sim):
        if i % 10 == 0:
            room.append((ts(i), f"{round(v, 1):.1f}"))
    main = [(ts(0), "1"), (ts(90), "4"), (ts(200), "1")]
    fan = [(ts(0), "0"), (ts(90), str(640 + 1.3 * 92 * 5.25)), (ts(200), "0")]
    series = {R: room, O: [(ts(0), "3.0")], M: main, F: fan, D: [(ts(0), "0")],
              "sun.sun": [(ts(0), "below_horizon")]}

    manager = LearningManager(hass, "xyz")
    manager.configure_history(R, O, M, F, D)

    async def fake(_s, _e):
        return series

    manager._fetch_history = fake  # type: ignore[assignment]
    report = await manager.async_bootstrap(now)
    assert report["chauffes"] == 1 and report["echantillons"] > 300, report
    assert manager.n_runs == 1, manager.data["last_fit"]
    assert manager.data["bootstrapped"]
    assert 1.8 < manager.model.a100 < 2.4

    # relancer ne ré-apprend pas la même chauffe
    again = await manager.async_bootstrap(now + timedelta(minutes=1))
    assert again["chauffes"] == 0 and manager.n_runs == 1

