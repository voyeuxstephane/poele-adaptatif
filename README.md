# Poêle adaptatif — intégration Home Assistant (version 0.3.1)

Intégration personnelle pour piloter le poêle Rika (via l'intégration **Rika Firenet** déjà installée) :
calendrier des heures de chauffe, consigne, anticipation réglable et toutes les commandes de la carte
« Poêle » du dashboard. **Les simulations de chauffe ne sont pas incluses** (étape suivante). La version 0.3 apprend toute seule le comportement thermique du salon.

## Installation

1. Copier le dossier `custom_components/poele_adaptatif` dans `/config/custom_components/`.
2. Redémarrer Home Assistant.
3. Réglages → Appareils et services → Ajouter une intégration → **Poêle adaptatif**.
4. Vérifier les entités proposées (déjà pré-remplies avec celles de ton poêle) puis valider.

## État du poêle et plages Rika (corrigé en 0.2.1)

- L'interrupteur « marche / arrêt » Rika reste sur `on` en permanence avec la planification Rika : il veut
  dire « poêle activé », pas « poêle allumé ». L'intégration utilise donc l'**état principal** du poêle
  (`sensor.salon_le_poele_le_poele_main_state`) : 2 à 5 = allumage / marche / nettoyage = poêle allumé ;
  1 = arrêt ou veille ; 6 = extinction.
- Les allumages et arrêts sont suivis sur cet état : « allumé par l'intégration » n'est retenu que si
  l'allumage suit une commande de l'intégration depuis moins de 30 minutes.
- **Tant que « Plages horaires Rika » est activé, l'intégration n'envoie aucune commande**, même si le pilotage
  est actif (sinon la planification du poêle et l'intégration l'allumeraient chacune à leur heure). La
  décision reste calculée et visible, avec l'attribut `commande_bloquee_par_plages_rika`.
- Si l'interrupteur marche/arrêt est déjà sur `on`, l'allumage se limite à passer en Confort et à régler la
  consigne : c'est le thermostat du poêle qui allume.

## Sécurité : le pilotage est coupé par défaut

L'interrupteur **Pilotage automatique** est à `off` à la création. Tant qu'il est coupé, l'intégration
calcule ses décisions (visibles dans « Dernière décision ») mais **n'envoie aucune commande** au poêle.
Les commandes manuelles (mode, boutons +/−, marche/arrêt…) fonctionnent toujours.

## Entités créées (appareil « Poêle adaptatif »)

> Les identifiants ci-dessous sont sans zone. Si l'appareil est placé dans une zone (chez toi **Salon**),
> Home Assistant préfixe les identifiants : `sensor.salon_poele_adaptatif_derniere_decision`, etc.

| Besoin | Entité | Rôle |
|---|---|---|
| Calendrier | `calendar.poele_adaptatif_plages_de_chauffe` | Plages de chauffe, modifiables dans l'onglet Calendrier |
| Consigne | `number.poele_adaptatif_consigne` | Consigne de la régulation (14–28 °C, pas 0,5) |
| | `number.poele_adaptatif_hysteresis` | Hystérésis (0,5 °C par défaut) |
| Anticipation | `select.poele_adaptatif_anticipation` | Désactivée / Fixe / **Apprise** |
| | `number.poele_adaptatif_avance_d_allumage` | Avance en minutes (mode Fixe, 90 min par défaut) |
| | `number.poele_adaptatif_puissance_de_chauffe_prevue_0_apprise` | Puissance supposée pendant la chauffe ; **0 = apprise** (défaut) |
| | `number.poele_adaptatif_avance_maximale_apprise` | Plafond de l'avance (mode Apprise, 180 min) |
| | `sensor.poele_adaptatif_duree_de_chauffe_estimee` | Minutes nécessaires, poêle allumé maintenant, pour atteindre la consigne |
| | `number.poele_adaptatif_marche_minimale` | Pas d'allumage court (60 min) |
| | `number.poele_adaptatif_delai_de_rallumage` | Pas de rallumage juste après un arrêt (30 min) |
| Pilotage | `switch.poele_adaptatif_pilotage_automatique` | Interrupteur général (off par défaut) |
| Commandes du poêle | `select.poele_adaptatif_mode` | Confort / Auto / Manuel (même logique que le dashboard) |
| | `switch.poele_adaptatif_marche_arret` | Marche / arrêt du poêle |
| | `switch.poele_adaptatif_plages_horaires_rika` | Plages horaires du poêle (Rika) |
| | `button.poele_adaptatif_plus` / `_moins` | Confort : consigne poêle ±1 °C ; sinon puissance ±5 % |
| | `number.poele_adaptatif_consigne_du_poele_rika` | Consigne propre du poêle (mode Confort) |
| | `number.poele_adaptatif_puissance_auto_manuel` | Puissance 30–100 % (Auto / Manuel) |
| Suivi | `sensor.poele_adaptatif_etat_du_poele` | Éteint / En veille / En chauffe / Extinction |
| | `sensor.poele_adaptatif_temperature_de_reference` | Sonde du salon utilisée |
| | `sensor.poele_adaptatif_prochain_allumage_prevu` | Avec l'anticipation |
| | `sensor.poele_adaptatif_fin_de_plage` | Fin de la plage en cours ou à venir |
| | `sensor.poele_adaptatif_derniere_decision` | Allumer / Éteindre / Aucune action, raison en attribut |
| | `sensor.poele_adaptatif_pellets_avant_entretien` | Recopie du capteur Rika |
| Apprentissage | `sensor.poele_adaptatif_etat_de_l_apprentissage` | Valeurs de départ / En apprentissage / Calibré, avec la dernière analyse |
| | `sensor.poele_adaptatif_perte_de_la_maison_k_apprise` | k (1/h), appris la nuit |
| | `sensor.poele_adaptatif_montee_a_100_apprise` | Montée à 100 % de puissance (°C/h) |
| | `sensor.poele_adaptatif_latence_d_allumage_apprise` | Délai avant que le salon réagisse (min) |
| | `sensor.poele_adaptatif_inertie_de_chauffe_apprise` | Inertie : chaleur qui continue après l'arrêt (min) |
| | `sensor.poele_adaptatif_puissance_habituelle_apprise` | Puissance relative habituelle du poêle (%) |
| | `button.poele_adaptatif_reinitialiser_l_apprentissage` | Repart des valeurs de départ (rarement utile) |
| | `button.poele_adaptatif_apprendre_sur_l_historique` | Apprend sur les chauffes déjà enregistrées |
| | `binary_sensor.poele_adaptatif_plage_active` | Une plage est en cours |

## Calendrier

Au premier démarrage, trois événements récurrents sont créés d'après la capture de l'appli Rika
(heures lues à l'œil, à ajuster) :

- lundi → vendredi : 05:00–06:40 et 15:00–22:00 ;
- samedi et dimanche : 05:30–22:00.

Tu peux créer, modifier et supprimer des plages (avec récurrence) depuis l'onglet **Calendrier** de
Home Assistant. Limites : seuls les événements avec une heure sont acceptés (pas « toute la journée »), et la
modification d'un événement récurrent s'applique à toute la série.

## Règles de régulation (version 0.1, sans simulation)

Quand le pilotage est actif :

1. On chauffe pendant les plages, et pendant l'**avance** avant la prochaine plage si l'anticipation est « Fixe ».
2. **Allumage** (poêle non allumé d'après son état principal) seulement si le salon est sous *consigne − hystérésis*. L'intégration passe le poêle en
   **Confort**, règle sa consigne (arrondie à l'entier), puis l'allume : le poêle module et s'arrête seul.
3. **Pas d'allumage court** : on n'allume pas si la plage se termine dans moins de la marche minimale.
4. **Pas de rallumage** dans le délai de rallumage qui suit un arrêt.
5. **Extinction** à la fin de la plage, uniquement si c'est l'intégration qui a allumé (un allumage manuel
   n'est jamais coupé), et jamais avant la marche minimale. Une seule commande est envoyée à l'arrêt, car
   l'intégration Rika remet `on` à chaque commande.
6. Deux commandes automatiques sont séparées d'au moins 5 minutes (cloud Rika lent).

## Apprentissage automatique du salon (nouveau en 0.3)

Plus rien à corriger à la main : l'intégration apprend elle-même cinq paramètres à partir de ce que fait
vraiment le poêle.

**Ce qu'elle mesure.** Chaque minute : température du salon, température extérieure, puissance réelle du
poêle (déduite du ventilateur), poêle allumé ou non, jour ou nuit. Les 72 dernières heures sont gardées.

**Comment elle apprend.**
- **Après chaque chauffe** (une heure après l'arrêt, pour voir la chaleur résiduelle), elle ajuste le modèle
  sur toute la courbe de température : montée à 100 %, latence d'allumage et inertie. L'ajustement est
  accepté seulement si la chauffe a duré au moins 45 min, si les données sont complètes, si le poêle était
  froid avant l'allumage et si l'écart entre modèle et mesure reste sous 0,25 °C. Sinon la chauffe est
  ignorée et la raison est visible dans « État de l'apprentissage ».
- **Toutes les 6 heures**, elle réestime k (perte de la maison) sur les périodes calmes de nuit, poêle éteint
  depuis plus d'1 h 30.
- Chaque mesure est mélangée à l'ancienne valeur (la première pèse 60 %, les suivantes 30 %) : un essai
  atypique ne dérègle pas le modèle, mais il rattrape vite un changement durable (saison, isolation, vent).
- La puissance habituelle du poêle en Confort est apprise de la même façon.

**Ce qu'elle en fait.** Le mode d'anticipation « Apprise » estime à chaque minute la durée nécessaire pour
atteindre la consigne au début de la plage (modèle appris, température du salon et extérieure du moment) et
allume à `début de plage − durée estimée`, dans la limite de l'avance maximale. Une fois allumé pour une
plage, le poêle reste allumé jusqu'à cette plage même si l'estimation diminue.

Les valeurs de départ (montée 1,6 °C/h, k 0,02 /h, latence 15 min, inertie 20 min, puissance 92 %) viennent
de tes chauffes du 15 et du 23/11. Elles sont remplacées par les valeurs apprises au fil des chauffes : compte
3 chauffes pour que le modèle soit « calibré ». Les paramètres appris et les échantillons survivent aux
redémarrages.

**Validation.** Sur une chauffe simulée de paramètres connus, l'ajustement retrouve la montée à ±0,25 °C/h ;
sur le rejeu approché de ta chauffe du 23/11 au matin, il donne une montée d'environ 2,1 °C/h (le départ
était 1,6), compatible avec les 1,6 à 2,0 mesurés ce jour-là. Aucune donnée réelle n'a été apprise avant
l'installation : les premières valeurs apprises seront celles de tes prochaines chauffes.

## Amorçage sur l'historique (nouveau en 0.3.1)

À la première installation de cette version, l'intégration relit l'historique enregistré par Home Assistant
(recorder, jusqu'à 70 h) : température du salon, extérieure, état principal, ventilateur et soleil. Elle
reconstitue les échantillons minute par minute et met en attente les chauffes déjà passées, qui sont ensuite
ajustées comme les autres (mêmes critères d'acceptation, une chauffe déjà apprise n'est jamais comptée deux
fois). Les chauffes trop proches l'une de l'autre (poêle encore chaud) sont écartées, la raison est visible
dans « État de l'apprentissage ». Le bouton **Apprendre sur l'historique** (catégorie configuration) relance
l'opération à la demande ; l'attribut `amorce_sur_historique` donne la date du dernier amorçage.
Limite : l'historique plus ancien que 66 h n'est pas utilisable (durée de conservation des échantillons).

## Ce qui est volontairement laissé pour la suite

- Prise en compte du vent et du soleil dans l'estimation (le salon est au nord : effet probablement faible).
- Réduction progressive de la puissance, simulations de chauffe et comparaison avec le poêle.
- Mode « Auto » : comme dans l'automatisation actuelle, il ne touche pas à l'interrupteur des plages Rika.

## Tests

Les tests (`tests/`, 26) ont été exécutés avec `pytest-homeassistant-custom-component` sur Home Assistant
**2025.1.4** (Python 3.12) : logique de planning, création des entités, calendrier, décisions, commandes,
flux de configuration, persistance. Ils n'ont pas été exécutés sur ta version de Home Assistant, et la lecture réelle du recorder n'est testée qu'avec un simulacre : à vérifier sur ton installation.

```
pip install pytest-homeassistant-custom-component
touch custom_components/__init__.py
python -m pytest
```

## Exemple de carte pour le dashboard

```yaml
type: entities
title: Poêle adaptatif
entities:
  - entity: switch.poele_adaptatif_pilotage_automatique
  - entity: select.poele_adaptatif_mode
  - entity: switch.poele_adaptatif_marche_arret
  - entity: sensor.poele_adaptatif_etat_du_poele
  - entity: number.poele_adaptatif_consigne
  - entity: select.poele_adaptatif_anticipation
  - entity: number.poele_adaptatif_avance_d_allumage
  - entity: sensor.poele_adaptatif_prochain_allumage_prevu
  - entity: sensor.poele_adaptatif_derniere_decision
  - entity: calendar.poele_adaptatif_plages_de_chauffe
```
