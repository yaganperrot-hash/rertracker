"""
recalcul.py — Reconstruit toutes les métriques journalières depuis les incidents bruts.

À lancer après tout changement de la logique de calcul (profils horaires, pondération,
fréquentation) : `python -m backend.recalcul`.

Les incidents ne sont jamais touchés — seules les `daily_metrics`, qui en dérivent, sont
réécrites. L'opération est donc rejouable autant de fois que nécessaire.
Le serveur doit être arrêté : sinon le scheduler écrit dans la même base en parallèle.
"""
import asyncio
from datetime import date, timedelta

from sqlalchemy import func, select

from backend.bilans import generer_bilans
from backend.database import AsyncSessionLocal
from backend.metrics import PARIS_TZ, compute_daily_metrics
from backend.models import Incident


async def _plage_des_incidents() -> tuple[date, date] | None:
    """Premier et dernier jour de service couverts par les incidents en base.

    On itère ensuite sur toutes les dates de la plage plutôt que de calculer en SQL la
    fenêtre 7 h → 7 h : un jour sans incident ne coûte rien (compute_daily_metrics n'écrit
    alors rien) et on évite une expression de fuseau difficile à relire.
    """
    async with AsyncSessionLocal() as db:
        borne = (await db.execute(
            select(func.min(Incident.heure_debut), func.max(Incident.heure_debut))
        )).one()
    debut, fin = borne
    if debut is None or fin is None:
        return None
    # Un incident à 3 h du matin appartient au jour de service précédent (fenêtre 7 h → 7 h)
    return (debut.astimezone(PARIS_TZ).date() - timedelta(days=1),
            fin.astimezone(PARIS_TZ).date())


async def recalculer() -> None:
    plage = await _plage_des_incidents()
    if plage is None:
        print("Aucun incident en base — rien à recalculer.")
        return

    debut, fin = plage
    jours = [debut + timedelta(days=i) for i in range((fin - debut).days + 1)]
    print(f"{len(jours)} jours à recalculer : {debut} → {fin}")
    for j in jours:
        await compute_daily_metrics(target_date=j)
        print(f"  {j} ✓", flush=True)

    await generer_bilans()
    print("Bilans régénérés")


def main() -> None:
    asyncio.run(recalculer())


if __name__ == "__main__":
    main()
