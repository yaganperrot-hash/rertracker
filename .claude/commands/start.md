---
description: Début de session — lecture de l'état, restitution, plan.
---
Lis `.claude/SESSION.md`, `TODO.md` et `.claude/DEBUG.md` (`memory/lessons.md` si pertinent).

**Transfert inter-PC** (temporaire — retirer après migration VPS) :
Vérifie si des fichiers `transferts/*.json` existent. Si oui, importe-les un par un :
```bash
python -m backend.transfert import transferts/<fichier>.json
```
Signale combien de fichiers ont été importés (ou « aucun transfert en attente »).

Restitue en 3 lignes max : objectif courant, où on en est, prochaine étape.
Propose ensuite un plan priorisé pour cette session.
Attends ma validation explicite avant d'écrire la moindre ligne.

$ARGUMENTS