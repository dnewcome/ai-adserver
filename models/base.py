from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from config import settings

engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(AsyncAttrs, DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session


@asynccontextmanager
async def task_session():
    """
    Session for use inside Celery tasks (asyncio.run() context).
    Uses NullPool to avoid sharing connections across event loops.
    """
    task_engine = create_async_engine(settings.database_url, echo=False, poolclass=NullPool)
    session_factory = async_sessionmaker(task_engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            yield session
    finally:
        await task_engine.dispose()
