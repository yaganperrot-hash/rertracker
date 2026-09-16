"""Réétiquetage des Transilien J, K et U (correctif du 2026-09-15).

Jusqu'au 2026-09-15, LIGNES_CIBLES pointait J, K et U sur les identifiants PRIM des lignes
P, R et N : tout ce qui est enregistré sous J / K / U appartient en réalité à P / R / N.
(L, N, P et R pointaient sur des bus ou sur rien : aucune donnée à corriger.)

    ./venv/bin/python -m backend.relabel_transilien
    ./venv/bin/python -m backend.relabel_transilien --statut   # lecture seule : déjà appliqué ou non

Une seule fois par base, serveur arrêté, juste après le pull du correctif et avant de relancer le
serveur. Ordre des transferts : importer d'abord ceux exportés AVANT le correctif (anciennes
étiquettes), puis lancer ce script, puis seulement importer ceux exportés APRÈS (ex.
incidents-2026-09-15.json du Mac) — sinon leurs vrais J / K / U seraient renommés à tort.
Les données J / K / U relevées ensuite sont justes — une table témoin (migrations_appliquees)
empêche donc toute seconde exécution.
Sauvegardes : incidents_backup_20260915, daily_metrics_backup_20260915.
"""
import asyncio
import sys

from sqlalchemy import text

from backend.bilans import generer_bilans
from backend.database import AsyncSessionLocal
from backend.metrics import compute_daily_metrics

NOM = "relabel_transilien_20260915"
CORRECTION = {"TRANSILIEN_J": "TRANSILIEN_P", "TRANSILIEN_K": "TRANSILIEN_R", "TRANSILIEN_U": "TRANSILIEN_N"}

_CASE = "CASE line_id " + " ".join(f"WHEN '{a}' THEN '{b}'" for a, b in CORRECTION.items()) + " END"
_ANCIENS = ", ".join(f"'{a}'" for a in CORRECTION)


async def deja_applique() -> bool:
    """Lecture seule : ne crée pas la table témoin si elle n'existe pas encore."""
    async with AsyncSessionLocal() as session:
        if await session.scalar(text("SELECT to_regclass('migrations_appliquees')")) is None:
            return False
        return bool(await session.scalar(text("SELECT 1 FROM migrations_appliquees WHERE nom = :nom"), {"nom": NOM}))


async def reetiqueter() -> None:
    async with AsyncSessionLocal() as session:
        await session.execute(text(
            "CREATE TABLE IF NOT EXISTS migrations_appliquees "
            "(nom VARCHAR(100) PRIMARY KEY, applique_a TIMESTAMPTZ NOT NULL DEFAULT now())"
        ))
        deja = await session.scalar(text("SELECT 1 FROM migrations_appliquees WHERE nom = :nom"), {"nom": NOM})
        if deja:
            await session.commit()
            print("Réétiquetage déjà appliqué sur cette base — rien à faire")
            return

        await session.execute(text("CREATE TABLE IF NOT EXISTS incidents_backup_20260915 AS SELECT * FROM incidents"))
        await session.execute(text(
            "CREATE TABLE IF NOT EXISTS daily_metrics_backup_20260915 AS SELECT * FROM daily_metrics"
        ))
        nb_incidents = (await session.execute(text(
            f"UPDATE incidents SET line_id = {_CASE} WHERE line_id IN ({_ANCIENS})"
        ))).rowcount
        # Supprimer les métriques à l'ancienne étiquette qui entreraient en conflit
        # avec une ligne déjà présente sous la bonne étiquette (ex. serveur lancé après le fix)
        for ancien, nouveau in CORRECTION.items():
            await session.execute(text(
                "DELETE FROM daily_metrics WHERE line_id = :ancien "
                "AND date IN (SELECT date FROM daily_metrics WHERE line_id = :nouveau)"
            ), {"ancien": ancien, "nouveau": nouveau})
        jours = sorted(set((await session.execute(text(
            f"UPDATE daily_metrics SET line_id = {_CASE} WHERE line_id IN ({_ANCIENS}) RETURNING date"
        ))).scalars()))
        await session.execute(text("INSERT INTO migrations_appliquees (nom) VALUES (:nom)"), {"nom": NOM})
        await session.commit()
    print(f"{nb_incidents} incidents reetiquetes (J->P, K->R, U->N), {len(jours)} journees de metriques")

    # Fréquentation différente d'une ligne à l'autre : minutes-voyageurs et coûts à recalculer
    for jour in jours:
        await compute_daily_metrics(target_date=jour)
        print(f"Métriques recalculées pour {jour}")
    await generer_bilans()
    print("Bilans régénérés")


def main(argv: list[str]) -> None:
    if argv == ["--statut"]:
        if asyncio.run(deja_applique()):
            print("Réétiquetage : déjà appliqué sur cette base")
        else:
            print("Réétiquetage : pas encore appliqué sur cette base")
    elif not argv:
        asyncio.run(reetiqueter())
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main(sys.argv[1:])
