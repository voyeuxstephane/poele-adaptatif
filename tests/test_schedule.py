"""Tests de la logique pure (sans Home Assistant) : python3 tests/test_schedule.py"""
import importlib.util
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

path = Path(__file__).parent.parent / "custom_components" / "poele_adaptatif" / "schedule.py"
spec = importlib.util.spec_from_file_location("schedule", path)
sch = importlib.util.module_from_spec(spec)
sys.modules["schedule"] = sch
spec.loader.exec_module(sch)

TZ = ZoneInfo("Europe/Paris")


def dt(d, h, m=0):
    return datetime(2026, 11, d, h, m, tzinfo=TZ)


events = sch.default_events(TZ)

# --- occurrences : semaine du lundi 23 au dimanche 29 novembre 2026 ------------
occ = sch.all_occurrences(events, dt(23, 0), dt(30, 0))
windows = sch.merge_windows([(s, e) for s, e, _, _ in occ])
# 5 jours x 2 plages + 2 jours x 1 plage = 12 plages
assert len(windows) == 12, len(windows)
assert windows[0] == (dt(23, 5, 0), dt(23, 6, 40)), windows[0]
assert windows[1] == (dt(23, 15, 0), dt(23, 22, 0)), windows[1]
assert windows[-1] == (dt(29, 5, 30), dt(29, 22, 0)), windows[-1]

# --- sérialisation : l'heure murale est conservée -------------------------------
back = sch.StoredEvent.from_dict(events[0].to_dict())
assert back.start == events[0].start and back.rrule == events[0].rrule

# --- fusion de plages qui se touchent -----------------------------------------
m = sch.merge_windows([(dt(23, 5), dt(23, 7)), (dt(23, 7), dt(23, 9)), (dt(23, 12), dt(23, 13))])
assert m == [(dt(23, 5), dt(23, 9)), (dt(23, 12), dt(23, 13))], m

# --- changement d'heure : 5h00 reste 5h00 le lundi 30 mars 2026 (été) ----------
ev = sch.StoredEvent("x", "t", datetime(2026, 3, 23, 5, 0, tzinfo=TZ), datetime(2026, 3, 23, 6, 0, tzinfo=TZ), "FREQ=WEEKLY;BYDAY=MO")
o = sch.occurrences(ev, datetime(2026, 3, 29, 12, tzinfo=TZ), datetime(2026, 3, 31, 12, tzinfo=TZ))
assert o[0][0].hour == 5 and o[0][0].utcoffset() == timedelta(hours=2), o

base = dict(
    stove_on=False, started_by_us=False, room_temp=18.0, consigne=20.0, hysteresis=0.5,
    anticipation_minutes=0, min_run_minutes=60, cooldown_minutes=30,
    last_start=None, last_stop=None,
)


def run(now, **kw):
    args = {**base, **kw}
    return sch.decide(now, windows, **args)


# 1. début de plage, pièce froide -> allumer
d = run(dt(24, 15, 5))
assert d.action == "start" and d.in_window, d

# 2. pièce déjà chaude -> ne rien faire
d = run(dt(24, 15, 5), room_temp=19.8)
assert d.action == "none" and "suffisante" in d.reason, d

# 3. pas d'anticipation : à 13h00 on n'allume pas
d = run(dt(24, 13, 0))
assert d.action == "none" and not d.heating_wanted, d

# 4. anticipation de 120 min : à 13h05 on allume pour 15h00
d = run(dt(24, 13, 5), anticipation_minutes=120)
assert d.action == "start" and not d.in_window and "anticipation" in d.reason, d
assert d.next_start == dt(24, 13, 0), d.next_start

# 5. anticipation : trop tôt à 12h30
d = run(dt(24, 12, 30), anticipation_minutes=120)
assert d.action == "none", d

# 6. rallumage différé après un arrêt récent
d = run(dt(24, 15, 5), last_stop=dt(24, 14, 50))
assert d.action == "none" and "différé" in d.reason, d

# 7. allumage court évité : plage finit dans 30 min
d = run(dt(24, 21, 30))
assert d.action == "none" and "court" in d.reason, d

# 8. fin de plage : extinction si c'est nous qui avons allumé
d = run(dt(24, 22, 5), stove_on=True, started_by_us=True, last_start=dt(24, 15, 5))
assert d.action == "stop", d

# 9. allumage manuel : on ne l'éteint pas
d = run(dt(24, 22, 5), stove_on=True, started_by_us=False, last_start=dt(24, 21, 0))
assert d.action == "none", d

# 10. marche minimale pas atteinte (plage courte 5h00-6h40, allumée à 6h10)
d = run(dt(24, 6, 45), stove_on=True, started_by_us=True, last_start=dt(24, 6, 10))
assert d.action == "none" and "minimale" in d.reason, d

# 11. température inconnue -> pas d'allumage
d = run(dt(24, 15, 5), room_temp=None)
assert d.action == "none" and "indisponible" in d.reason, d

# 12. hors plage la nuit, prochaine plage = 5h00 le lendemain avec avance 90
d = run(dt(24, 23, 0), anticipation_minutes=90)
assert d.next_start == dt(25, 3, 30), d.next_start

# --- estimateur de durée de chauffe ------------------------------------------
est = sch.estimate_heating_minutes
kw = dict(a100=1.4, k=0.0245, power_pct=90, latency_min=20)
assert est(20.2, 20.0, 5.0, **kw) == 0                      # déjà atteinte
m_cold = est(18.0, 20.0, 5.0, **kw)
m_mild = est(19.5, 20.0, 5.0, **kw)
assert 120 <= m_cold <= 180, m_cold                          # matin froid : ~2 h 30
assert 20 < m_mild < m_cold, (m_mild, m_cold)               # plus court si on part de plus haut
assert est(18.0, 20.0, 5.0, a100=1.4, k=0.0245, power_pct=90, latency_min=20) < est(18.0, 20.0, 5.0, a100=1.4, k=0.0245, power_pct=90, latency_min=60)
assert est(18.0, 20.0, 5.0, a100=0.2, k=0.05, power_pct=50, latency_min=20, max_minutes=300) == 300  # inatteignable
# plus froid dehors -> plus long
assert est(18.0, 20.0, -5.0, **kw) > est(18.0, 20.0, 10.0, **kw)

# --- maintien : après un allumage en anticipation, on ne coupe pas avant la plage -
upcoming_start = dt(24, 15, 0)
common = dict(started_by_us=True, room_temp=19.5, consigne=20.0, hysteresis=0.5,
              min_run_minutes=60, cooldown_minutes=30, last_start=dt(24, 12, 30), last_stop=None)
# avance recalculée à 0 (pièce déjà proche) : sans maintien on couperait
d = sch.decide(dt(24, 14, 0), windows, stove_on=True, anticipation_minutes=0, anticipating_for=None, **common)
assert d.action == "stop", d
d = sch.decide(dt(24, 14, 0), windows, stove_on=True, anticipation_minutes=0, anticipating_for=upcoming_start, **common)
assert d.action == "none" and d.heating_wanted and d.anticipating, d
assert d.window_start == upcoming_start, d.window_start
# le maintien ne vaut que pour la plage visée
d = sch.decide(dt(24, 14, 0), windows, stove_on=True, anticipation_minutes=0, anticipating_for=dt(25, 5, 0), **common)
assert d.action == "stop", d

print("OK : tous les tests de schedule.py passent")
