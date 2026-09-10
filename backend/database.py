from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from backend.config import get_settings


class Base(DeclarativeBase):
    pass


def get_engine():
    settings = get_settings()
    url = settings.database_url
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return create_async_engine(url, echo=False)


engine = get_engine()
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all n'ajoute pas les colonnes aux tables existantes
        for col, typ in (("gare", "VARCHAR(120)"), ("direction", "VARCHAR(120)"), ("mission", "VARCHAR(20)")):
            await conn.execute(text(f"ALTER TABLE incidents ADD COLUMN IF NOT EXISTS {col} {typ}"))
    # Backfill source and is_cancelled for existing data
    from backend.migrate_source import backfill_source
    async with AsyncSessionLocal() as session:
        await backfill_source(session)
