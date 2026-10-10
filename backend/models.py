from datetime import datetime, date
from sqlalchemy import (
    Integer, String, Text, DateTime, Date, Boolean, BigInteger,
    UniqueConstraint, func
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from backend.database import Base


class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    navitia_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    line_id: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    type_incident: Mapped[str] = mapped_column(String(50), nullable=False)
    cause: Mapped[str | None] = mapped_column(Text, nullable=True)
    heure_debut: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    heure_fin: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duree_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    source: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)
    heure_theorique: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_cancelled: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    gare: Mapped[str | None] = mapped_column(String(120), nullable=True)
    direction: Mapped[str | None] = mapped_column(String(120), nullable=True)
    mission: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Lignes impactées par la perturbation (disruptions multi-lignes) :
    # ["RER_A", "RER_B", "RER_D"]. Pour les incidents RT (retards/suppressions), [line_id].
    # Null pour les anciens incidents d'avant la bascule (fallback sur [line_id] dans le code).
    lignes_impactees: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # Arrêts du train relevés dans le flux SIRI Estimated Timetable, dans l'ordre du parcours :
    # [{"g": gare, "p": heure prévue ISO UTC, "r": retard à l'arrivée (min) ou null,
    #   "s": arrêt supprimé, "w": attente mesurée du train suivant (min) ou null}]. Null avant la bascule.
    # none_as_null : None s'écrit NULL SQL, pas le JSON « null » (qui passait pour des arrêts relevés en SQL)
    arrets: Mapped[list | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DailyMetric(Base):
    __tablename__ = "daily_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    line_id: Mapped[str] = mapped_column(String(20), nullable=False)
    nb_incidents: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duree_totale_min: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    minutes_voyageurs: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    nb_rt_delays: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nb_disruptions: Mapped[int | None] = mapped_column(Integer, nullable=True)
    nb_cancelled: Mapped[int | None] = mapped_column(Integer, nullable=True)
    est_jour_perturbe: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("date", "line_id", name="uq_daily_metrics_date_line"),
    )
