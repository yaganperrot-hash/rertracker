"""
Backfill migration for source, is_cancelled columns.

Called once after create_all() in init_db().
Sets source='realtime' for DELAY_REALTIME incidents without source,
source='disruption' for all others without source,
and is_cancelled=False for all NULL is_cancelled.
"""
import logging

from sqlalchemy import update, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Incident

logger = logging.getLogger(__name__)


async def backfill_source(session: AsyncSession) -> None:
    """Backfill source and is_cancelled for existing data."""

    # Set source='realtime' for DELAY_REALTIME without source
    stmt_rt = (
        update(Incident)
        .where(Incident.source.is_(None), Incident.type_incident == "DELAY_REALTIME")
        .values(source="realtime")
    )
    result_rt = await session.execute(stmt_rt)
    logger.info("Backfilled source='realtime' for %d rows", result_rt.rowcount)

    # Set source='disruption' for all others without source
    stmt_disr = (
        update(Incident)
        .where(Incident.source.is_(None))
        .values(source="disruption")
    )
    result_disr = await session.execute(stmt_disr)
    logger.info("Backfilled source='disruption' for %d rows", result_disr.rowcount)

    # Set is_cancelled=False for all NULL
    stmt_cancel = (
        update(Incident)
        .where(Incident.is_cancelled.is_(None))
        .values(is_cancelled=False)
    )
    result_cancel = await session.execute(stmt_cancel)
    logger.info("Backfilled is_cancelled=False for %d rows", result_cancel.rowcount)

    await session.commit()
