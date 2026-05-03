"""
SROP entrypoint — called by the message route.

This implements the core orchestration pipeline:
  - Load session state from DB
  - Determine routing intent (knowledge, account, smalltalk)
  - Call appropriate agent with context
  - Extract tool calls and responses
  - Record trace
  - Persist state

Simple routing: Uses keyword matching for MVP. Full LLM-based routing can be added.
State persistence: Pattern 3 (SessionState in context) + full message history in DB.
"""
import asyncio
import structlog
import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql import select

from app.agents.knowledge import knowledge_agent
from app.agents.account import account_agent
from app.agents.tools.search_docs import search_docs
from app.agents.tools.account_tools import get_recent_builds, get_account_status
from app.api.errors import UpstreamTimeoutError, SessionNotFoundError
from app.db.models import Session, Message, AgentTrace, User
from app.settings import settings
from app.srop.state import SessionState

log = structlog.get_logger()


@dataclass
class PipelineResult:
    content: str
    routed_to: str
    trace_id: str


def determine_routing(user_message: str, last_agent: str | None) -> str:
    """
    Determine which agent should handle this message.
    
    Simple MVP routing based on keywords.
    - If user asks "my builds", "my status", "my account" → account
    - If user asks "how", "what is", docs questions → knowledge
    - Follow-ups default to last_agent if set
    - Otherwise → knowledge (default)
    """
    msg_lower = user_message.lower()
    
    # Account keywords
    account_keywords = [
        "my builds", "my account", "my status", "my usage",
        "builds failed", "builds passed", "concurrent", "storage",
        "plan tier", "recent builds", "build status", "build history",
        "failed builds", "passed builds", "pipeline"
    ]
    
    # Knowledge keywords
    knowledge_keywords = [
        "how do", "how to", "how can", "what is", "what are",
        "show me", "explain", "tell me", "documentation", "deploy key",
        "configure", "setup", "rotate", "webhook", "secret", "artifact"
    ]
    
    for keyword in account_keywords:
        if keyword in msg_lower:
            return "account"
    
    for keyword in knowledge_keywords:
        if keyword in msg_lower:
            return "knowledge"
    
    # Follow-ups: use last_agent if set
    if last_agent and last_agent in ["knowledge", "account"]:
        return last_agent
    
    # Default to knowledge
    return "knowledge"


async def run(session_id: str, user_message: str, db: AsyncSession) -> PipelineResult:
    """
    Run one turn of the SROP pipeline.

    Process:
    1. Load session state and prior messages from DB
    2. Determine routing intent
    3. Call appropriate agent
    4. Extract response and tool calls
    5. Write trace record
    6. Update and persist session state
    7. Return response

    Raises:
        SessionNotFoundError: if session not found
        UpstreamTimeoutError: if LLM timeout
    """
    trace_id = str(uuid.uuid4())
    start_time = time.time()

    structlog.contextvars.bind_contextvars(
        session_id=session_id,
        trace_id=trace_id,
    )

    log.info("pipeline_started", user_message_len=len(user_message))

    # 1. Load session, user, and state from DB
    stmt = select(Session).where(Session.session_id == session_id).options(selectinload(Session.user))
    result = await db.execute(stmt)
    session_row = result.scalar_one_or_none()

    if not session_row:
        log.warning("session_not_found")
        raise SessionNotFoundError(f"Session {session_id} not found")

    user_id = session_row.user_id
    state = SessionState.from_db_dict(session_row.state) if session_row.state else SessionState(
        user_id=user_id,
        plan_tier=session_row.user.plan_tier if session_row.user else "free",
    )

    log.info("session_loaded", user_id=user_id, plan_tier=state.plan_tier, turn_count=state.turn_count)

    # 2. Load prior messages from DB
    msg_stmt = select(Message).where(Message.session_id == session_id).order_by(Message.created_at)
    msg_result = await db.execute(msg_stmt)
    prior_messages = msg_result.scalars().all()

    log.info("message_history_loaded", prior_message_count=len(prior_messages))

    # 3. Determine routing
    routed_to = determine_routing(user_message, state.last_agent)
    log.info("routing_determined_intent", routed_to=routed_to)

    # 4. Prepare agent context
    user_context = f"""
User Information:
- user_id: {state.user_id}
- plan_tier: {state.plan_tier}
- previous_agent: {state.last_agent}
- conversation_turn: {state.turn_count}

Use this context to provide personalized responses.
"""

    tool_calls = []
    retrieved_chunk_ids = []
    reply_content = ""

    try:
        # 5. Call the appropriate agent
        if routed_to == "knowledge":
            # Knowledge agent: use search_docs tool for RAG
            reply_content, chunk_ids = await _run_knowledge_agent(
                user_message, user_context, search_docs
            )
            retrieved_chunk_ids = chunk_ids
            tool_calls = [{"tool_name": "search_docs", "args": {"query": user_message, "k": 5}}] if chunk_ids else []

        elif routed_to == "account":
            # Account agent: use account tools
            reply_content, calls = await _run_account_agent(
                user_message, state.user_id, user_context, get_recent_builds, get_account_status
            )
            tool_calls = calls

        else:
            # Smalltalk: respond directly
            reply_content = "Hi! How can I help you with Helix today?"
            routed_to = "smalltalk"

        log.info(
            "routing_determined",
            routed_to=routed_to,
            tool_calls_count=len(tool_calls),
            chunk_ids_count=len(retrieved_chunk_ids),
        )

    except asyncio.TimeoutError:
        log.warning("orchestrator_timeout", timeout_seconds=settings.llm_timeout_seconds)
        raise UpstreamTimeoutError(
            f"LLM did not respond within {settings.llm_timeout_seconds} seconds"
        )
    except Exception as e:
        log.exception("orchestrator_error", error=str(e))
        raise

    # Fallback
    if not reply_content:
        reply_content = "I encountered an issue processing your request. Please try again."

    # 6. Write trace record to DB
    trace_record = AgentTrace(
        trace_id=trace_id,
        session_id=session_id,
        routed_to=routed_to,
        tool_calls=tool_calls,
        retrieved_chunk_ids=retrieved_chunk_ids,
        latency_ms=int((time.time() - start_time) * 1000),
    )
    db.add(trace_record)

    # 7. Update session state and persist to DB
    state.last_agent = routed_to
    state.turn_count += 1
    session_row.state = state.to_db_dict()
    session_row.updated_at = datetime.utcnow()

    # 8. Store messages
    user_msg = Message(
        message_id=str(uuid.uuid4()),
        session_id=session_id,
        role="user",
        content=user_message,
        trace_id=trace_id,
    )
    assistant_msg = Message(
        message_id=str(uuid.uuid4()),
        session_id=session_id,
        role="assistant",
        content=reply_content,
        trace_id=trace_id,
    )

    db.add(user_msg)
    db.add(assistant_msg)

    try:
        await db.commit()
        log.info("session_persisted")
    except Exception as e:
        log.exception("session_persist_error", error=str(e))
        await db.rollback()
        raise

    return PipelineResult(
        content=reply_content,
        routed_to=routed_to,
        trace_id=trace_id,
    )


async def _run_knowledge_agent(
    user_message: str,
    context: str,
    search_docs_fn,
) -> tuple[str, list[str]]:
    """
    Run the knowledge agent to answer documentation questions.
    
    Returns:
        (reply_text, list_of_chunk_ids_retrieved)
    """
    # For MVP: search docs directly and construct a response
    try:
        search_result = await search_docs_fn(user_message, k=5)
        
        chunk_ids = []
        if "results" in search_result:
            results = search_result["results"]
            chunk_ids = [r.get("chunk_id") for r in results if r.get("chunk_id")]
            
            if results:
                # Construct response with citations
                response_parts = [f"{context}\n\nBased on our documentation:\n\n"]
                for i, result in enumerate(results[:3], 1):
                    content = result.get("content", "")[:200]  # First 200 chars
                    chunk_id = result.get("chunk_id", "")
                    source = result.get("source", "")
                    score = result.get("score", 0)
                    
                    response_parts.append(
                        f"[{chunk_id}] ({source}, relevance: {score:.1%})\n{content}...\n"
                    )
                
                return "\n".join(response_parts), chunk_ids
        
        return f"{context}\n\nI searched the documentation but didn't find a specific answer to '{user_message}'. Could you provide more details?", chunk_ids
        
    except Exception as e:
        log.exception("knowledge_agent_error", error=str(e))
        return f"I encountered an error searching the documentation: {str(e)}", []


async def _run_account_agent(
    user_message: str,
    user_id: str,
    context: str,
    get_builds_fn,
    get_status_fn,
) -> tuple[str, list[dict]]:
    """
    Run the account agent to answer account/usage questions.
    
    Returns:
        (reply_text, list_of_tool_calls)
    """
    tool_calls = []
    
    try:
        # Check account status
        status_result = await get_status_fn(user_id)
        tool_calls.append({"tool_name": "get_account_status", "args": {"user_id": user_id}})
        
        # Check recent builds if asked
        builds_result = await get_builds_fn(user_id, limit=3)
        tool_calls.append({"tool_name": "get_recent_builds", "args": {"user_id": user_id, "limit": 3}})
        
        # Construct response
        response_parts = [context]
        
        if "error" not in status_result:
            response_parts.append("\n**Your Account Status:**")
            response_parts.append(f"- Plan: {status_result.get('plan_tier')}")
            response_parts.append(f"- Concurrent builds: {status_result.get('concurrent_builds_used')}/{status_result.get('concurrent_builds_limit')}")
            response_parts.append(f"- Storage: {status_result.get('storage_used_gb'):.1f}GB / {status_result.get('storage_limit_gb'):.1f}GB")
        
        if "builds" in builds_result and builds_result["builds"]:
            response_parts.append("\n**Recent Builds:**")
            for build in builds_result["builds"][:3]:
                status_emoji = "✓" if build.get("status") == "passed" else "✗"
                response_parts.append(
                    f"{status_emoji} {build.get('pipeline')} ({build.get('branch')}) - {build.get('status')}"
                )
        
        return "\n".join(response_parts), tool_calls
        
    except Exception as e:
        log.exception("account_agent_error", error=str(e))
        return f"I encountered an error retrieving your account information: {str(e)}", tool_calls
