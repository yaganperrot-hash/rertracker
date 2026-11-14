# Alertes Telegram — « une ligne dégénère »

À chaque relevé temps réel (toutes les 5 min, `backend/main.py`), `backend/alertes.py` regarde les trains retardés ou
supprimés relevés dans la dernière heure, ligne par ligne, avec le même calcul que le site. Si une ligne dégénère,
il envoie sur Telegram une image 1200×675 et un post X prêt à copier, avec un bouton « Ouvrir dans X ».
La publication sur X reste manuelle.

## Déclencheur

Une ligne déclenche si, sur les `ALERTE_FENETRE_MIN` dernières minutes :
- son coût atteint `ALERTE_SEUIL_EUROS`, ou
- un train a au moins `ALERTE_DUREE_INCIDENT_MIN` de retard **et** le coût atteint
  `ALERTE_SEUIL_EUROS × ALERTE_RATIO_SEUIL_INCIDENT`.

Anti-spam : `ALERTE_MAX_JOUR` alertes par jour au total, une par ligne toutes les `ALERTE_DELAI_LIGNE_H` heures,
rien entre `ALERTE_SILENCE_DEBUT` h et `ALERTE_SILENCE_FIN` h (Paris). Les envois sont notés dans
`publications/alertes/etat.json` (dossier monté sur le VPS, conservé aux redéploiements, ignoré par git).
Une alerte dont l'envoi échoue n'est pas notée : elle sera retentée au relevé suivant si la ligne déclenche encore.

## Variables (`.env` du VPS)

| Variable | Défaut | |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | token donné par @BotFather (obligatoire) |
| `TELEGRAM_CHAT_ID` | — | identifiant de la conversation (obligatoire) |
| `ALERTE_SEUIL_EUROS` | 100000 | coût sur la fenêtre qui déclenche seul |
| `ALERTE_DUREE_INCIDENT_MIN` | 30 | retard d'un train qui abaisse le seuil |
| `ALERTE_RATIO_SEUIL_INCIDENT` | 0.8 | seuil abaissé = seuil × ratio |
| `ALERTE_FENETRE_MIN` | 60 | fenêtre glissante (min) |
| `ALERTE_MAX_JOUR` | 2 | alertes par jour, toutes lignes |
| `ALERTE_DELAI_LIGNE_H` | 3 | délai minimal entre deux alertes d'une même ligne |
| `ALERTE_SILENCE_DEBUT` / `_FIN` | 22 / 6 | silence de nuit, heure de Paris |

Sans token ni chat_id, rien n'est envoyé (un warning par alerte dans les logs) ; la collecte n'est jamais affectée.

**Trouver le chat_id** : créer le bot avec @BotFather, lui écrire un message, puis ouvrir
`https://api.telegram.org/bot<TOKEN>/getUpdates` : la valeur est dans `"chat":{"id": …}`.
Après modification du `.env` : `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`.

## Essayer et calibrer

Dans le conteneur du site (`docker exec -it rertracker-backend-1 …`) :

```bash
# Évalue maintenant et affiche l'alerte (texte, image, lien X) sans rien envoyer — même sous le seuil, même la nuit
python -m backend.alertes --dry-run

# Alertes qu'auraient données les seuils actuels sur les 14 derniers jours (jours complets),
# puis balayage de seuils et proposition d'un ALERTE_SEUIL_EUROS donnant 3 à 5 alertes par semaine
python -m backend.alertes backtest --jours 14
python -m backend.alertes backtest --jours 14 --seuils 80000,100000,120000
```

Le backtest rejoue relevé par relevé (toutes les 5 min, de 6 h à minuit) avec l'anti-spam. Limite : il lit chaque
train dans son état final en base, pas tel qu'il était au moment du relevé ; le coût d'une heure en cours de
journée est donc un peu surestimé par rapport au direct.

Calibrage du 2026-11-11 (28/10 → 10/11) : 100 000 € et ratio 0,8 → 4 alertes par semaine
(90 000 € → 6, 110 000 € → 3). À refaire après quelques semaines de données.
