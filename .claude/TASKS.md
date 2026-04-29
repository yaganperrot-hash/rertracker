# TASKS Deepseek

## TASK-01 — Ajouter `duree_minutes` et corriger `heure_fin` dans /api/incidents/current

### Fichier cible
`backend/api.py`

### Contexte
L'endpoint `GET /api/incidents/current` (ligne 41-52) retourne une liste d'incidents.
Deux champs sont manquants/incorrects :
1. `duree_minutes` n'est pas inclus dans la réponse → le frontend ne peut pas calculer le coût
2. `heure_fin` est hardcodé à `None` au lieu d'utiliser la vraie valeur du modèle

### Code actuel (lignes 41-52)
```python
return [
    {
        "id": r.id,
        "navitia_id": r.navitia_id,
        "line_id": r.line_id,
        "type_incident": r.type_incident,
        "cause": r.cause,
        "heure_debut": r.heure_debut.isoformat(),
        "heure_fin": None,   # ← FAUX : hardcodé
    }
    for r in rows
]
```

### Correction attendue
```python
return [
    {
        "id": r.id,
        "navitia_id": r.navitia_id,
        "line_id": r.line_id,
        "type_incident": r.type_incident,
        "cause": r.cause,
        "heure_debut": r.heure_debut.isoformat(),
        "heure_fin": r.heure_fin.isoformat() if r.heure_fin else None,
        "duree_minutes": r.duree_minutes,   # ← à ajouter
    }
    for r in rows
]
```

### Critères d'acceptation
- `GET /api/incidents/current` retourne `duree_minutes` (int ou null) pour chaque incident
- `heure_fin` retourne la vraie valeur ISO 8601 si elle existe, sinon `null`
- Aucune autre modification dans le fichier
