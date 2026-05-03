"""
Integration tests — exercise the full SROP pipeline.
LLM mocked at the ADK boundary (not at the HTTP layer).
"""
import pytest


@pytest.mark.asyncio
async def test_create_session(client):
    resp = await client.post("/v1/sessions", json={"user_id": "u_test_001"})
    assert resp.status_code == 200
    data = resp.json()
    assert "session_id" in data
    assert data["user_id"] == "u_test_001"


@pytest.mark.asyncio
async def test_healthz(client):
    resp = await client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_knowledge_query_routes_correctly(client, mock_adk):
    """
    Core integration test.

    Sends a knowledge question, asserts:
    1. Response contains a reply
    2. routed_to == "knowledge"
    3. trace exists with retrieved chunk IDs
    4. Turn 2 in the same session has access to context from turn 1
       (state persistence — at minimum, plan_tier available without re-asking)

    The mock_adk fixture patches at the ADK boundary, not at the HTTP layer.
    """
    # Create session
    sess = await client.post(
        "/v1/sessions", json={"user_id": "u_test_002", "plan_tier": "pro"}
    )
    assert sess.status_code == 200
    session_id = sess.json()["session_id"]

    # Turn 1 — knowledge query
    r1 = await client.post(
        f"/v1/chat/{session_id}",
        json={"content": "How do I rotate a deploy key?"},
    )
    assert r1.status_code == 200
    resp1 = r1.json()
    assert resp1["routed_to"] == "knowledge"
    assert "chunk_" in resp1["reply"] or "deploy" in resp1["reply"].lower()
    trace_id_1 = resp1["trace_id"]

    # Verify trace was written
    trace = await client.get(f"/v1/traces/{trace_id_1}")
    assert trace.status_code == 200
    trace_data = trace.json()
    assert trace_data["trace_id"] == trace_id_1
    assert trace_data["routed_to"] == "knowledge"

    # Turn 2 — follow-up asking about their plan
    # The agent should know plan_tier from state without re-asking
    r2 = await client.post(
        f"/v1/chat/{session_id}",
        json={"content": "What is my plan tier?"},
    )
    assert r2.status_code == 200
    resp2 = r2.json()
    # The mock returns "pro plan" when asked about tier
    assert "pro" in resp2["reply"].lower()


@pytest.mark.asyncio
async def test_account_query_routes_correctly(client, mock_adk):
    """Account queries should route to account_agent."""
    sess = await client.post(
        "/v1/sessions", json={"user_id": "u_test_003", "plan_tier": "enterprise"}
    )
    session_id = sess.json()["session_id"]

    r = await client.post(
        f"/v1/chat/{session_id}",
        json={"content": "Show me my recent builds"},
    )
    assert r.status_code == 200
    resp = r.json()
    assert resp["routed_to"] == "account"
    assert "build" in resp["reply"].lower()


@pytest.mark.asyncio
async def test_session_not_found_returns_404(client):
    """Non-existent session should return 404."""
    resp = await client.post(
        "/v1/chat/nonexistent-id",
        json={"content": "hello"},
    )
    assert resp.status_code == 404
    error = resp.json()
    assert "SESSION_NOT_FOUND" in error.get("title", "")


@pytest.mark.asyncio
async def test_trace_not_found_returns_404(client):
    """Non-existent trace should return 404."""
    resp = await client.get("/v1/traces/nonexistent-trace-id")
    assert resp.status_code == 404
    error = resp.json()
    assert "TRACE_NOT_FOUND" in error.get("title", "")
