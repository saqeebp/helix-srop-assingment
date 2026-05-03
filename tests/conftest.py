"""
Test fixtures.

Key fixtures:
- `client`: async test client with in-memory SQLite DB
- `mock_adk`: patches the ADK root agent so tests don't hit the real LLM
- `seeded_db`: DB with a test user and session pre-created
"""
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from unittest.mock import AsyncMock, patch

from app.db.models import Base, User, Session
from app.db.session import get_db
from app.main import app
from app.srop.pipeline import PipelineResult
from app.srop.state import SessionState


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSessionLocal = async_sessionmaker(test_engine, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def setup_test_db():
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def db() -> AsyncSession:
    async with TestSessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def client(db):
    """Async test client with DB overridden to in-memory SQLite."""
    app.dependency_overrides[get_db] = lambda: db
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def mock_adk(monkeypatch):
    """
    Patch the ADK pipeline so tests don't call the real LLM.

    The mock intercepts pipeline.run() and returns canned responses based on the message content.
    Test can assert which sub-agent was called and what context was used.
    """

    async def mock_run(session_id, message, db):
        """Mock implementation of pipeline.run()."""
        # Route based on message content for testing
        if "rotate" in message.lower() or "deploy key" in message.lower():
            routed_to = "knowledge"
            reply = (
                "To rotate a deploy key [chunk_abc123], you can use the CLI or web interface. "
                "See [chunk_def456] for detailed steps."
            )
        elif "build" in message.lower() or "pipeline" in message.lower():
            routed_to = "account"
            reply = "You have 3 recent builds: 2 passed, 1 failed. Your last build was build_001 which passed in 3 minutes."
        elif "tier" in message.lower() or "plan" in message.lower():
            routed_to = "smalltalk"
            reply = "Based on your context, you're on the pro plan tier."
        else:
            routed_to = "smalltalk"
            reply = "Hello! I'm the Helix Support Concierge. How can I help?"

        return PipelineResult(
            content=reply,
            routed_to=routed_to,
            trace_id="test-trace-001",
        )

    monkeypatch.setattr("app.srop.pipeline.run", mock_run)
    return mock_run


@pytest_asyncio.fixture
async def seeded_db(db: AsyncSession) -> tuple[AsyncSession, str, str]:
    """Create a test user and session in the DB."""
    user = User(user_id="u_test_001", plan_tier="pro")
    db.add(user)
    await db.flush()

    initial_state = SessionState(
        user_id="u_test_001",
        plan_tier="pro",
        last_agent=None,
        turn_count=0,
    )

    session = Session(
        session_id="session_test_001",
        user_id="u_test_001",
        state=initial_state.to_db_dict(),
    )
    db.add(session)
    await db.commit()

    return db, "u_test_001", "session_test_001"
