"""
Shared fixtures for the test suite.

DB strategy: session-scoped engine → function-scoped connection with an outer
BEGIN that wraps every test; route-level `db.commit()` calls become SAVEPOINTs
via `join_transaction_mode="create_savepoint"`, so the outer transaction can
be rolled back after each test without touching the schema.

Redis strategy: `auction.cache._redis` is patched to return a FakeRedis
instance shared within each test (autouse, function-scoped).
"""
import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import fakeredis.aioredis
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

import models.advertiser  # noqa: F401 — register all mappers
import models.campaign    # noqa: F401
import models.conversion  # noqa: F401
import models.impression  # noqa: F401
import models.publisher   # noqa: F401
from main import app
from models.base import Base, get_db

TEST_DB_URL = (
    "postgresql+asyncpg://adserver@/adserver_test"
    "?host=/var/run/postgresql&port=5433"
)


# ---------------------------------------------------------------------------
# Event loop — one per session
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


# ---------------------------------------------------------------------------
# Database engine — created once per session, tables created/dropped around it
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(TEST_DB_URL, poolclass=NullPool, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


# ---------------------------------------------------------------------------
# Per-test DB session — wrapped in a transaction that is always rolled back
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    async with test_engine.connect() as conn:
        await conn.begin()
        session = AsyncSession(
            bind=conn,
            expire_on_commit=False,
            join_transaction_mode="create_savepoint",
        )
        yield session
        await session.close()
        await conn.rollback()


# ---------------------------------------------------------------------------
# HTTP client — uses the test session via dependency override
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Redis mock — patches auction.cache._redis for the duration of each test
# ---------------------------------------------------------------------------

class _FakeRedisCtx:
    """Wraps a FakeRedis so it works as `async with _redis() as r:`."""
    def __init__(self, r):
        self._r = r

    async def __aenter__(self):
        return self._r

    async def __aexit__(self, *_):
        pass


@pytest.fixture(autouse=True)
def mock_redis(monkeypatch):
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr("auction.cache._redis", lambda: _FakeRedisCtx(r))
    return r


# ---------------------------------------------------------------------------
# Seed helpers — build common objects directly in the DB session
# ---------------------------------------------------------------------------

async def create_advertiser(db, email="adv@test.com", password="pass", balance=100.0):
    from passlib.context import CryptContext
    from models.advertiser import Advertiser
    hashed = CryptContext(schemes=["bcrypt"]).hash(password)
    adv = Advertiser(email=email, hashed_password=hashed, company_name="Test Co", balance_usd=balance)
    db.add(adv)
    await db.flush()
    return adv


async def create_publisher(db, email="pub@test.com", password="pass"):
    from passlib.context import CryptContext
    from models.publisher import Publisher
    hashed = CryptContext(schemes=["bcrypt"]).hash(password)
    pub = Publisher(email=email, hashed_password=hashed, site_url="https://test-pub.com")
    db.add(pub)
    await db.flush()
    return pub


async def create_campaign(db, advertiser_id, categories=None, bid_floor=5.0, creatives=None):
    from models.campaign import Campaign, CampaignStatus
    campaign = Campaign(
        advertiser_id=advertiser_id,
        product_url="https://example.com/product",
        brand_name="Test Brand",
        suggested_categories=categories or ["IAB19-18", "IAB19"],
        bid_floor_cpm=bid_floor,
        ad_creatives=creatives or [
            {
                "variant_id": "A",
                "headline_short": "Buy Now",
                "headline_long": "Buy This Product Now",
                "body_copy": "Great product.",
                "cta": "Shop",
                "image_url": None,
            }
        ],
        status=CampaignStatus.ACTIVE,
        is_listed=True,
    )
    db.add(campaign)
    await db.flush()
    return campaign


async def create_zone(db, publisher_id, categories=None):
    from models.publisher import InventoryZone
    zone = InventoryZone(
        publisher_id=publisher_id,
        name="test-banner",
        zone_type="banner",
        dimensions="728x90",
        categories=categories or ["IAB19-18", "IAB19"],
    )
    db.add(zone)
    await db.flush()
    return zone


async def create_impression(db, zone_id, campaign_id, cpm=5.01, clicked=False):
    from models.impression import Impression
    imp = Impression(
        zone_id=zone_id,
        campaign_id=campaign_id,
        cpm_paid=cpm,
        clicked=clicked,
    )
    db.add(imp)
    await db.flush()
    return imp


async def get_token(client, email, password):
    resp = await client.post(
        "/auth/login",
        data={"username": email, "password": password},
    )
    return resp.json()["access_token"]
