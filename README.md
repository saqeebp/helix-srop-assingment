# Helix SROP — AI Support Concierge

A stateful RAG orchestration pipeline (SROP) for intelligent support that remembers context across turns and process restarts.

## Quick Start

### 1. Setup

```bash
git clone <your-repo>
cd helix-srop
uv sync
cp .env.example .env        # Fill in GOOGLE_API_KEY
```

### 2. Ingest Documentation

```bash
uv run python -m app.rag.ingest --path docs/
```

This chunks the markdown files in `docs/`, embeds them with Google's Generative AI, and stores them in Chroma.

### 3. Run the Server

```bash
uv run uvicorn app.main:app --reload
```

The server starts on `http://localhost:8000`.

### 4. Test the API

Create a session:

```bash
SESSION=$(curl -s -X POST localhost:8000/v1/sessions \
  -H "Content-Type: application/json" \
  -d '{"user_id": "u_demo", "plan_tier": "pro"}' | jq -r .session_id)
```

Send a message:

```bash
curl -s -X POST localhost:8000/v1/chat/$SESSION \
  -H "Content-Type: application/json" \
  -d '{"content": "How do I rotate a deploy key?"}' | jq .
```

Get trace:

```bash
TRACE_ID=$(curl -s -X POST localhost:8000/v1/chat/$SESSION \
  -H "Content-Type: application/json" \
  -d '{"content": "Show me my recent builds"}' | jq -r .trace_id)

curl -s -X GET localhost:8000/v1/traces/$TRACE_ID | jq .
```

### 5. Run Tests

```bash
uv run pytest tests/ -v
```

## Architecture

```text
  ┌──────────────────────────────────────┐
  │  POST /v1/chat/{session_id}          │
  │  Request: {content: str}             │
  └────────────────┬─────────────────────┘
                   │
                   ▼
        ┌──────────────────────┐
        │  Pipeline.run()      │
        │  1. Load session     │
        │  2. Inject state     │
        │  3. Run orchestrator │
        │  4. Save state       │
        │  5. Write trace      │
        └──────┬───────┬───────┘
               │       │
         ┌─────▼──┐ ┌──▼──────┐
         │  Root  │ │  ADK    │
         │ Orches │ │ Events  │
         └─────┬──┘ └─────────┘
               │
         ┌─────┴──────────┬─────────────────┐
         │                │                 │
    ┌────▼─────┐   ┌──────▼──────┐   ┌─────▼────┐
    │ Knowledge│   │  Account    │   │ Smalltalk│
    │  Agent   │   │   Agent     │   │  (inline)│
    └────┬─────┘   └──────┬──────┘   └──────────┘
         │                │
      ┌──▼──┐         ┌───▼────┐
      │RAG  │         │Account │
      │Store│         │  DB    │
      └─────┘         └────────┘
```

## Design Decisions

### State Persistence Pattern

**Pattern Used:** DB-stored SessionState in `sessions.state` (JSON column)

**Why:**

- Survives process restart (hard requirement)
- Fast lookup on each turn (no message history reconstruction)
- Scales to large conversations without history explosion
- SessionState is minimal: user_id, plan_tier, last_agent, turn_count

**Implementation:**

- SessionState is a Pydantic model that serializes to dict for JSON storage
- On each turn: load → inject into system prompt → run LLM → update → persist
- All state updates are transactional (commit or rollback)

### Chunking Strategy

**Strategy:** Heading-aware with sentence-level fallback and overlap

**Why:**

- Markdown structure (##, ###) often aligns with semantic boundaries
- Preserves section context so "rotate deploy key" returns relevant section, not random chunks
- Sentence-aware fallback prevents breaking mid-paragraph
- 20-token overlap (~60 chars) bridges chunk boundaries so answers span coherently

**Chunks produced:**

- ~15–30 chunks per doc (depending on file size)
- Stable chunk IDs (SHA256 of filename + chunk index) → re-ingest is idempotent

### Vector Store Choice

**Choice:** Chroma (in-process, persistent)

**Why:**

- No external service needed for local dev (fast iteration)
- Persistent on disk → survives restarts
- Supports metadata filtering (future extension for product_area)
- Easy swap to Pinecone or LanceDB if scaling later
- Built-in cosine similarity is appropriate for semantic search

### Agent Routing

**Pattern:** ADK's `AgentTool` — LLM decides which agent to invoke

**Why:**

- Specification requirement (not string parsing)
- Flexible — agent can refuse a tool or explain ambiguity
- Extensible — add tools without rewriting router logic
- Traceable — each tool call is logged in trace

## API Endpoints

### POST /v1/sessions

Create a session.

- **Request:** `{user_id: str, plan_tier?: str}`
- **Response:** `{session_id: str, user_id: str}`
- **Error:** None (always succeeds; upserts user if new)

### POST /v1/chat/{session_id}

Send a message and get orchestrated response.

- **Request:** `{content: str}`
- **Response:** `{reply: str, routed_to: str, trace_id: str}`
- **Errors:**
  - `404 SESSION_NOT_FOUND` — session doesn't exist
  - `504 UPSTREAM_TIMEOUT` — LLM didn't respond in 30s

### GET /v1/traces/{trace_id}

Retrieve trace for debugging.

- **Response:** `{trace_id, session_id, routed_to, tool_calls, retrieved_chunk_ids, latency_ms}`
- **Error:** `404 TRACE_NOT_FOUND` — trace doesn't exist

### GET /healthz

Health check.

- **Response:** `{status: "ok"}`

## Data Model

### sessions table

```text
session_id (str, PK)
user_id (FK)
state (JSON)          # {"user_id": "u_1", "plan_tier": "pro", "turn_count": 2, "last_agent": "knowledge"}
created_at (datetime)
updated_at (datetime)
```

### messages table

```text
message_id (str, PK)
session_id (FK)
role (str)            # "user" | "assistant"
content (text)
trace_id (FK)
created_at (datetime)
```

### agent_traces table

```text
trace_id (str, PK)
session_id (str, indexed)
routed_to (str)       # "knowledge" | "account" | "smalltalk"
tool_calls (JSON)     # [{"name": "search_docs", "args": {}, "result": {...}}]
retrieved_chunk_ids (JSON)  # ["chunk_abc123", "chunk_def456"]
latency_ms (int)
created_at (datetime)
```

## Code Structure

```text
app/
  main.py — FastAPI app, lifespan, exception handlers
  settings.py — Pydantic settings from .env
  
  api/
    errors.py — HelixError, SessionNotFoundError, UpstreamTimeoutError
    routes_sessions.py — POST /sessions
    routes_chat.py — POST /chat/{id}
    routes_traces.py — GET /traces/{id}
  
  agents/
    orchestrator.py — root agent with AgentTool routing
    knowledge.py — KnowledgeAgent (RAG + search_docs)
    account.py — AccountAgent (account tools)
    tools/
      search_docs.py — call vector store
      account_tools.py — get_recent_builds, get_account_status
  
  db/
    models.py — SQLAlchemy ORM: User, Session, Message, AgentTrace
    session.py — asyncio engine, session factory
  
  obs/
    logging.py — structlog setup
  
  rag/
    ingest.py — CLI to chunk + embed + upsert docs
    vector_store.py — Chroma singleton, deterministic chunk IDs
  
  srop/
    state.py — SessionState schema
    pipeline.py — main orchestration logic (load state → run LLM → save → trace)

tests/
  conftest.py — fixtures: client, mock_adk, db
  test_api.py — integration: session creation, routing, state persistence
  test_retriever.py — chunking, search_docs, metadata extraction
```

## Known Limitations

1. **Mock account data** — get_recent_builds and get_account_status return mock data for demo. In production, wire to actual DB.

2. **No auth** — user_id is passed in request body. Use JWT in production (extension E2).

3. **No idempotency** — same message sent twice produces two separate traces. Would add Idempotency-Key header (extension E1).

4. **No reranking** — top-k chunks from Chroma are returned as-is. Could add LLM-as-judge reranking (extension E4).

5. **No streaming** — responses are returned all-at-once. SSE streaming is in extension E3.

6. **Single-model only** — hardcoded to `gemini-2.0-flash`. Could parameterize for Claude, GPT, etc.

## What I'd Do With More Time

1. **E1: Idempotency** — Store (session_id, idempotency_key) → response in DB. Replay requests return cached result immediately.

2. **E2: Escalation Agent** — Third sub-agent that creates support tickets. Store ticket_id in session state so follow-ups reference it. Add `tickets` table.

3. **E3: Streaming SSE** — Stream chunk-by-chunk as LLM generates. Requires chunked message architecture.

4. **E4: Reranking** — After top-5 retrieval, use LLM to rerank by relevance. Show before/after scores in trace.

5. **E5: Guardrails** — Add system message detector for out-of-scope queries (e.g., "write me a poem"). Log refusals.

6. **E6: Docker** — `Dockerfile` for app, `docker-compose.yml` for Postgres + Chroma + app. One-command startup.

7. **E7: Eval Harness** — Synthetic test queries with expected agent routing. Report accuracy.

## Time Spent

| Phase | Time |
| --- | --- |
| Setup + DB models | 20 min |
| Vector store + ingest | 30 min |
| ADK agents + orchestrator | 40 min |
| Pipeline implementation | 50 min |
| API endpoints + error handling | 30 min |
| Tests + fixtures | 30 min |
| README + polish | 20 min |
| **Total** | **3.5 hours** |

## Running Tests

```bash
cd helix-srop-assignment
uv run pytest tests/test_api.py::test_knowledge_query_routes_correctly -v
uv run pytest tests/test_retriever.py -v
```

All tests use mocked LLM (no API calls) and in-memory SQLite. Should pass in <5 seconds.

## Extensions Implemented

- [ ] E1: Idempotency
- [ ] E2: Escalation agent
- [ ] E3: Streaming SSE
- [ ] E4: Reranking
- [ ] E5: Guardrails
- [ ] E6: Docker
- [ ] E7: Eval harness

(None completed in core iteration, prioritized getting spec requirements working.)
