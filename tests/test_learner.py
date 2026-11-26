"""Tests de l'apprentissage (logique pure) : python3 tests/test_learner.py"""
import importlib.util
import random
import sys
from pathlib import Path

path = Path(__file__).parent.parent / "custom_components" / "poele_adaptatif" / "learner.py"
spec = importlib.util.spec_from_file_location("learner", path)
lr = importlib.util.module_from_spec(spec)
sys.modules["learner"] = lr
spec.loader.exec_module(lr)

random.seed(3)


def quantize(series, step=0.1, every=10):
    """Capteur réel : résolution 0,1 °C, mise à jour toutes les ~10 min."""
    out, held = [], None
    for i, v in enumerate(series):
        if i % every == 0:
            held = round(v / step) * step
        out.append(held)
    return out


# --- 1. une chauffe synthétique : les paramètres sont retrouvés ----------------
true = lr.Model(a100=1.7, k=0.02, latency=20, tau=20)
n = 90 + 100 + 60  # 90 min avant, 100 min de chauffe, 60 min après
power = [0.0] * 90 + [92.0] * 100 + [0.0] * 60
t_out = [3.0] * n
sim = lr.simulate(18.2, t_out, power, true)
room = quantize(sim)
fit = lr.fit_run(room, t_out, power, true.k)
assert fit is not None
assert abs(fit.a100 - 1.7) < 0.25, fit
assert abs(fit.latency - 20) <= 10, fit
assert fit.rmse < 0.1, fit

# --- 2. la même chauffe avec un k un peu faux : a100 reste raisonnable ---------
fit2 = lr.fit_run(room, t_out, power, 0.025)
assert fit2 is not None and 1.4 < fit2.a100 < 2.6 and fit2.rmse < 0.15, fit2

# --- 3. série trop courte -> None ----------------------------------------------
assert lr.fit_run(room[:50], t_out[:50], power[:50], 0.02) is None

# --- 4. k : refroidissement nocturne --------------------------------------------
k_true = 0.018
n = 600
t_out = [2.0 - 0.003 * i for i in range(n)]
temps = lr.free_response(20.2, t_out, k_true)
room = quantize(temps, every=10)
quiet = [True] * n
est = lr.estimate_k(room, t_out, quiet)
assert est is not None and abs(est[0] - k_true) < 0.005, est
# segment trop court : refusé
assert lr.estimate_k(room[:100], t_out[:100], [True] * 100) is None
# poêle allumé : rien à estimer
assert lr.estimate_k(room, t_out, [False] * n) is None

# --- 5. EMA ----------------------------------------------------------------------
assert abs(lr.ema(1.0, 2.0, 0) - 1.6) < 1e-9
assert abs(lr.ema(1.0, 2.0, 3) - 1.3) < 1e-9

# --- 6. durée estimée avec le modèle appris ---------------------------------------
m = lr.Model(a100=1.7, k=0.02, latency=20, tau=20)
cold = lr.minutes_to_reach(18.1, 20.0, 5.0, m, 92)
mild = lr.minutes_to_reach(19.5, 20.0, 5.0, m, 92)
assert lr.minutes_to_reach(20.2, 20.0, 5.0, m, 92) == 0
assert 100 <= cold <= 190 and 20 < mild < cold, (cold, mild)
assert lr.minutes_to_reach(18.0, 20.0, -5.0, m, 92) > lr.minutes_to_reach(18.0, 20.0, 10.0, m, 92)
assert lr.minutes_to_reach(18.0, 25.0, 5.0, lr.Model(0.3, 0.05, 20, 20), 50, max_minutes=300) == 300

# --- 7. rejeu approché de la chauffe du 23/11 au matin ---------------------------
# allumage 05:05, marche 05:11 -> 06:50 à ~92 %, extérieur ~1 °C ; mesures du salon
obs_pts = {0: 18.3, 43: 18.5, 63: 18.8, 83: 19.1, 93: 19.4, 103: 19.7, 115: 19.9, 125: 20.0, 135: 20.1, 145: 20.2, 165: 20.2}
n = 90 + 175  # 90 min de repos (03:35) puis 175 min jusqu'à ~08:00
power = [0.0] * (90 + 6) + [92.0] * 99 + [0.0] * (n - 90 - 6 - 99)
t_out = [1.0] * n
room = [None] * n
for m_, v in obs_pts.items():
    room[90 + m_ - 30 + 30] = v  # t=0 des mesures = 05:05
# on remplit le début pour que la série démarre à 18,3 °C
for i in range(0, 90):
    room[i] = 18.3 if i % 10 == 0 else None
f = lr.fit_run(room, t_out, power, 0.02, min_points=10)
assert f is not None, "ajustement impossible"
assert 1.2 <= f.a100 <= 2.6, f
print("rejeu 23/11 matin :", {k: round(v, 2) for k, v in f.__dict__.items()})

print("OK : tous les tests de learner.py passent")
