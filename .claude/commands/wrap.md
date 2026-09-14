---
description: Fin de session — met à jour l'état, archive, commit + push.
---
Clôture la session. Dans l'ordre :

1. `.claude/SESSION.md` : d'abord copier l'état courant vers `.claude/archive/session-<AAAA-MM-JJ>.md`,
   puis réécrire SESSION.md avec le SEUL état courant (objectif, avancement, blocage, prochaine étape).
   Pas d'empilement d'entrées dans le fichier vivant.
2. `.claude/DEBUG.md` : mettre à jour les bugs (résolus avec date / en cours) et ajouter les nouveaux.
3. `memory/lessons.md` : ajouter les leçons de la session (patterns, pièges, solutions). Toute leçon
   durable/récurrente → la promouvoir en règle dans CLAUDE.md et la retirer d'ici.
4. Si un fichier ou dossier a été créé, renommé ou supprimé → mettre à jour l'arbre de `README.md`.
5. Commit par unité logique + push. (Force-push / suppressions / réécriture d'historique → demander d'abord.)

$ARGUMENTS