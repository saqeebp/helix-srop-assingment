"""
POST /v1/sessions — create a session.
"""
import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import select

from app.db.models import User, Session
from app.db.session import get_db
from app.srop.state import SessionState

router = APIRouter(tags=["sessions"])


class CreateSessionRequest(BaseModel):
    user_id: str
    plan_tier: str = "free"


class CreateSessionResponse(BaseModel):
    session_id: str
    user_id: str


@router.post("/sessions", response_model=CreateSessionResponse)
async def create_session(
    body: CreateSessionRequest,
    db: AsyncSession = Depends(get_db),
) -> CreateSessionResponse:
    """
    Create a new session. Upsert the user if not seen before.
    Initialize SessionState and persist to DB.
    """
    session_id = str(uuid.uuid4())

    # Upsert user: check if exists, else create
    stmt = select(User).where(User.user_id == body.user_id)
    result = await db.execute(stmt)
    user_row = result.scalar_one_or_none()

    if not user_row:
        user_row = User(user_id=body.user_id, plan_tier=body.plan_tier)
        db.add(user_row)
        await db.flush()  # Ensure user is inserted before creating session
    else:
        # Update plan_tier if provided
        user_row.plan_tier = body.plan_tier
        await db.flush()

    # Create initial session state
    initial_state = SessionState(
        user_id=body.user_id,
        plan_tier=body.plan_tier,
        last_agent=None,
        turn_count=0,
    )

    # Create session with initial state
    session_row = Session(
        session_id=session_id,
        user_id=body.user_id,
        state=initial_state.to_db_dict(),
    )
    db.add(session_row)

    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return CreateSessionResponse(
        session_id=session_id,
        user_id=body.user_id,
    )
