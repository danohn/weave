import os

# Must be set before app modules are imported so pydantic-settings picks it up
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["REQUIRE_PREAUTH"] = "false"  # existing tests register without a token

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.config import settings
from app.db.base import Base, get_session
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"
ADMIN_TOKEN = "test-admin-token"

# StaticPool keeps the same in-memory connection so all sessions share state
test_engine = create_async_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create all tables before each test, drop them after."""
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.fixture
def make_session():
    """Return the test session factory so individual tests can open their own
    short-lived sessions for DB setup without holding a connection open."""
    return TestSessionLocal


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    """HTTP test client with the database dependency overridden."""

    async def override_get_session():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def secure_client() -> AsyncClient:
    """HTTPS test client so Secure session cookies are sent back to the app."""

    async def override_get_session():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="https://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client_require_preauth() -> AsyncClient:
    """HTTP test client with REQUIRE_PREAUTH forced on."""

    async def override_get_session():
        async with TestSessionLocal() as session:
            yield session

    app.dependency_overrides[get_session] = override_get_session

    original = settings.REQUIRE_PREAUTH
    settings.REQUIRE_PREAUTH = True
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            yield ac
    finally:
        settings.REQUIRE_PREAUTH = original
        app.dependency_overrides.clear()
