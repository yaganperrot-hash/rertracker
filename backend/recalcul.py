"""
recalcul.py — Reconstruit toutes les métriques journalières depuis les incidents bruts.

À lancer après tout changement de la logique de calcul (profils horaires, pondération,
fréquentation) : `python -m backend.recalcul`.

Seules les `daily_metrics`, qui dérivent des incidents, sont réécrites — plus une réparation des incidents :
un train dont un arrêt relevé est supprimé redevient « supprimé » (règle du collecteur), état perdu avant le
2026-09-18 par l'ancien collecteur et par l'import. L'opération est rejouable autant de fois que nécessaire.
Le serveur doit être arrêté : sinon le scheduler écrit dans la même base en parallèle.
"""
import asyncio
from datetime import date, datetime, timedelta

from sqlalchemy import func, select, update

from backend.bilans import generer_bilans
from backend.config import get_settings
from backend.database import AsyncSessionLocal
from backend.metrics import compute_daily_metrics, journee_de
from backend.models import Incident


async def _plage_des_incidents() -> tuple[date, date] | None:
    """Premier et dernier jour de service couverts par les incidents en base.

    On itère ensuite sur toutes les dates de la plage plutôt que de calculer en SQL la
    fenêtre de la journée comptée : un jour sans incident ne coûte rien (compute_daily_metrics n'écrit
    alors rien) et on évite une expression de fuseau difficile à relire.
    """
    async with AsyncSessionLocal() as db:
        borne = (await db.execute(
            select(func.min(Incident.heure_debut), func.max(Incident.heure_debut))
        )).one()
    debut, fin = borne
    if debut is None or fin is None:
        return None
    return journee_de(debut), journee_de(fin)


def premier_arret_supprime(arrets) -> dict | None:
    """Premier arrêt relevé supprimé d'un train (colonne `arrets`), None s'il n'y en a pas."""
    if not isinstance(arrets, list):
        return None
    return next((a for a in arrets if a.get("s") is True and a.get("p")), None)


async def nettoyer_arrets_json_null() -> int:
    """Arrêts enregistrés en JSON « null » par l'import d'avant le 2026-09-18 → NULL SQL."""
    async with AsyncSessionLocal() as db:
        res = await db.execute(update(Incident).where(func.jsonb_typeof(Incident.arrets) == "null").values(arrets=None))
        await db.commit()
    return res.rowcount


async def reparer_suppressions() -> int:
    """Remet « supprimé » les trains dont un arrêt relevé est supprimé mais enregistrés comme simples retards :
    même état que le collecteur (collector.analyser_train). Renvoie le nombre de trains réparés."""
    impact = get_settings().cancel_default_impact_minutes
    async with AsyncSessionLocal() as db:
        candidats = (await db.execute(select(Incident).where(
            Incident.source == "realtime", Incident.is_cancelled.isnot(True), Incident.arrets.isnot(None),
        ))).scalars().all()
        repares = 0
        for inc in candidats:
            arret = premier_arret_supprime(inc.arrets)
            if arret is None:
                continue
            gare = arret.get("g")
            await db.execute(update(Incident).where(Incident.id == inc.id).values(
                is_cancelled=True, type_incident="CANCELLED", duree_minutes=impact, gare=gare,
                heure_theorique=datetime.fromisoformat(arret["p"]),
                cause=f"Train supprimé à partir de {gare}" if gare else "Train supprimé",
            ))
            repares += 1
        await db.commit()
    return repares


async def recalculer() -> None:
    print(f"{await nettoyer_arrets_json_null()} incidents sans arrêts remis à NULL (JSON « null »)")
    print(f"{await reparer_suppressions()} trains remis « supprimé » d'après leurs arrêts")
    plage = await _plage_des_incidents()
    if plage is None:
        print("Aucun incident en base — rien à recalculer.")
        return

    debut, fin = plage
    jours = [debut + timedelta(days=i) for i in range((fin - debut).days + 1)]
    print(f"{len(jours)} jours a recalculer : {debut} -> {fin}")
    for j in jours:
        await compute_daily_metrics(target_date=j)
        print(f"  {j} ok", flush=True)

    await generer_bilans()
    print("Bilans régénérés")


def main() -> None:
    asyncio.run(recalculer())


if __name__ == "__main__":
    main()
