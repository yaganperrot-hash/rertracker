---
description: Début de session — lecture de l'état, restitution, plan.
---
Lis `.claude/SESSION.md`, `TODO.md` et `.claude/DEBUG.md` (`memory/lessons.md` si pertinent).

**Transfert inter-PC** (temporaire — retirer après migration VPS) :
`python` = le Python du venv du projet (`./venv/bin/python` sur Mac, `venv\Scripts\python` sous Windows).
Dans l'ordre, sans sauter d'étape :

1. **Serveur arrêté** : si un `uvicorn backend.main:app` tourne, le signaler et **ne rien importer** (il écrirait
   en même temps dans la base et consommerait le quota PRIM commun).
2. `git pull --ff-only`. En cas d'échec, s'arrêter et le signaler.
3. **Correctif Transilien** (J/K/U enregistrés à tort à la place de P/R/N jusqu'au 15/09) :
   ```bash
   python -m backend.relabel_transilien --statut
   ```
   Fichiers « d'avant le correctif » = `transferts/incidents-<date>.json` dont la date est **antérieure au
   2026-09-15** (le 13 et le 14) ; tous les autres sont « d'après ».
   - **« pas encore appliqué »** :
     a. importer les fichiers d'avant, du plus ancien au plus récent ;
     b. `python -m backend.relabel_transilien` (une seule fois) ;
     c. importer les fichiers d'après, du plus ancien au plus récent.
   - **« déjà appliqué »** : **ne jamais importer** les fichiers d'avant (leurs incidents absents de la base
     arriveraient avec la mauvaise lettre) ; importer seulement les fichiers d'après, du plus ancien au plus récent.
   - Toute autre sortie (erreur, base injoignable) : ne rien importer, le signaler.

   Import d'un fichier :
   ```bash
   python -m backend.transfert import transferts/<fichier>.json
   ```
4. Signale chaque fichier : importé (nombre d'incidents) ou ignoré, avec la raison ; « aucun transfert en attente »
   s'il n'y en a pas.
5. `POLLING_INTERVAL_MINUTES` dans `.env` : lire **uniquement cette ligne** (le reste contient des secrets). Si elle
   ne vaut pas 5, le signaler.
6. **Collecte en cours ?** `/start` ne lance jamais le serveur, et un serveur lancé en tâche de fond par Claude Code
   est tué : la collecte ne reprend que si l'utilisateur le lance dans son propre terminal.
   - Dernier incident de la base ou du dernier `transferts/incidents-<aujourd'hui>.json` : heure de Paris.
   - Si aucun serveur ne tourne sur ce PC, **commencer la restitution** par, en gras :
     « ⚠️ Aucune collecte sur ce PC depuis <heure>. L'autre PC tourne-t-il ? Sinon, chaque relevé manqué est perdu
     (PRIM n'expose pas l'historique). » — ne jamais supposer que l'autre PC collecte parce que sa session le dit.
   - Terminer la restitution par la commande de lancement, prête à copier :
     Mac : `cd ~/Desktop/Projets/rertracker && caffeinate -i ./venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000`
     Windows : `venv\Scripts\python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000` (veille désactivée).
     Rappeler : un seul serveur à la fois — couper l'autre PC avant de lancer celui-ci.

Restitue en 3 lignes max : objectif courant, où on en est, prochaine étape.
Propose ensuite un plan priorisé pour cette session.
Attends ma validation explicite avant d'écrire la moindre ligne.

$ARGUMENTS
