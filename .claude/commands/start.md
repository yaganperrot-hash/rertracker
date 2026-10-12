---
description: Début de session — lecture de l'état, restitution, plan.
---
Lis `.claude/SESSION.md`, `TODO.md` et `.claude/DEBUG.md` (`memory/lessons.md` si pertinent).

**Production sur VPS** (depuis le 2026-10-12 — voir `CLAUDE.md` → « Production » et `deploy/README.md`) :

1. `git pull --ff-only`. En cas d'échec, s'arrêter et le signaler.
2. **Pas de serveur collecteur sur ce PC** : si un `uvicorn backend.main:app` tourne ici, le signaler — il consomme
   le quota PRIM du VPS. `/start` ne lance jamais le serveur et n'importe plus les fichiers `transferts/`.
3. **Collecte du VPS** : ne jamais la supposer en marche. Si un accès SSH est disponible, lire les dernières lignes
   de log du backend (`docker compose logs --tail=50 backend`) et donner l'heure du dernier relevé ; sinon écrire
   « collecte du VPS non vérifiée » dans la restitution.

Restitue en 3 lignes max : objectif courant, où on en est, prochaine étape.
Propose ensuite un plan priorisé pour cette session.
Attends ma validation explicite avant d'écrire la moindre ligne.

$ARGUMENTS
