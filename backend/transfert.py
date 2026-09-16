"""Transfert des incidents d'un PC à l'autre (chaque PC a sa propre base).

    # PC de départ — serveur arrêté
    ./venv/bin/python -m backend.transfert export            # journée en cours (depuis 7 h)
    ./venv/bin/python -m backend.transfert export 2026-09-14

    # PC d'arrivée — après git pull, avant de lancer le serveur
    ./venv/bin/python -m backend.transfert import transferts/incidents-2026-09-14.json

L'import fusionne sur navitia_id (même identifiant sur les deux PC) avec la règle du collecteur :
pire retard observé, première heure vue, état (supprimé ou non) du relevé le plus récent.
Puis il recalcule les daily_metrics des journées touchées et les bilans.
"""
import asyncio
import json
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

from sqlalchemy import case, func, or_, select
from sqlalchemy.dialects.postgresql import insert

from backend.bilans import generer_bilans
from backend.database import AsyncSessionLocal
from backend.metrics import PARIS_TZ, compute_daily_metrics
from backend.models import Incident

DOSSIER = Path(__file__).parent.parent / "transferts"

COLONNES = [
    "navitia_id", "line_id", "type_incident", "cause", "heure_debut", "heure_fin", "duree_minutes",
    "created_at", "source", "heure_theorique", "is_cancelled", "gare", "direction", "mission", "updated_at",
    "arrets",
]
DATES = {"heure_debut", "heure_fin", "created_at", "heure_theorique", "updated_at"}


def _jour_service(dt: datetime) -> date:
    """Journée comptée depuis 7 h, heure de Paris (comme l'accueil et les bilans)."""
    return (dt.astimezone(PARIS_TZ) - timedelta(hours=7)).date()


def _ecrire_json(chemin: Path, contenu: dict) -> None:
    """Toujours en UTF-8 : sinon Windows écrit en cp1252 et le Mac ne relit pas le fichier."""
    chemin.write_text(json.dumps(contenu, ensure_ascii=False, indent=1), encoding="utf-8")


def _lire_json(chemin: Path) -> dict:
    """UTF-8, avec repli cp1252 pour les anciens exports faits sous Windows (13/09)."""
    try:
        texte = chemin.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        print(f"{chemin.name} n'est pas en UTF-8 : lecture en cp1252")
        texte = chemin.read_text(encoding="cp1252")
    return json.loads(texte)


async def exporter(jour: date) -> Path:
    debut = datetime.combine(jour, time(7, 0), tzinfo=PARIS_TZ)
    fin = debut + timedelta(days=1)
    async with AsyncSessionLocal() as session:
        stmt = select(Incident).where(or_(
            (Incident.heure_debut >= debut) & (Incident.heure_debut < fin),
            (Incident.updated_at >= debut) & (Incident.updated_at < fin),
        )).order_by(Incident.heure_debut)
        rows = (await session.execute(stmt)).scalars().all()

    donnees = [
        {c: (v.isoformat() if c in DATES and v is not None else v) for c in COLONNES for v in [getattr(r, c)]}
        for r in rows
    ]
    DOSSIER.mkdir(exist_ok=True)
    chemin = DOSSIER / f"incidents-{jour.isoformat()}.json"
    _ecrire_json(chemin, {"jour": jour.isoformat(), "incidents": donnees})
    print(f"{len(donnees)} incidents exportes -> {chemin}")
    return chemin


async def importer(chemin: Path) -> None:
    contenu = _lire_json(chemin)
    jours: set[date] = set()
    async with AsyncSessionLocal() as session:
        for brut in contenu["incidents"]:
            ligne = {c: (datetime.fromisoformat(v) if c in DATES and v is not None else v) for c, v in brut.items()}
            jours.add(_jour_service(ligne["heure_debut"]))

            stmt = insert(Incident).values(**ligne)
            ex = stmt.excluded
            plus_recent = ex.updated_at > Incident.updated_at
            # Retard temps réel des deux côtés : garder le pire, comme le collecteur
            deux_retards = (ex.is_cancelled.isnot(True)) & (Incident.is_cancelled.isnot(True)) \
                & (ex.source == "realtime") & (Incident.source == "realtime")
            pire = ex.duree_minutes > Incident.duree_minutes
            prendre = case((deux_retards, pire), else_=plus_recent)

            stmt = stmt.on_conflict_do_update(
                index_elements=["navitia_id"],
                set_={
                    "heure_debut": func.least(Incident.heure_debut, ex.heure_debut),
                    "created_at": func.least(Incident.created_at, ex.created_at),
                    "updated_at": func.greatest(Incident.updated_at, ex.updated_at),
                    **{c: case((prendre, getattr(ex, c)), else_=getattr(Incident, c))
                       for c in ("duree_minutes", "cause", "heure_theorique", "gare", "direction", "mission")},
                    **{c: case((plus_recent, getattr(ex, c)), else_=getattr(Incident, c))
                       for c in ("type_incident", "is_cancelled", "heure_fin", "source")},
                    # Un export d'avant la bascule n'a pas d'arrêts : ne pas effacer ceux déjà en base
                    "arrets": case((plus_recent, func.coalesce(ex.arrets, Incident.arrets)),
                                   else_=func.coalesce(Incident.arrets, ex.arrets)),
                },
            )
            await session.execute(stmt)
        await session.commit()
    print(f"{len(contenu['incidents'])} incidents fusionnés depuis {chemin}")

    for jour in sorted(jours):
        await compute_daily_metrics(target_date=jour)
        print(f"Métriques recalculées pour {jour}")
    await generer_bilans()
    print("Bilans régénérés")


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "export":
        jour = date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else _jour_service(datetime.now(PARIS_TZ))
        asyncio.run(exporter(jour))
    elif len(sys.argv) == 3 and sys.argv[1] == "import":
        asyncio.run(importer(Path(sys.argv[2])))
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
