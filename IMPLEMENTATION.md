# Implementation Summary — Helix SROP Assignment

## Overview

Completed a fully functional **Stateful RAG Orchestration Pipeline (SROP)** for an AI Support Concierge that:

- Routes user queries to specialized agents using Google ADK
- Maintains session state across process restarts
- Provides RAG-powered documentation search with chunk citations
- Traces all agent decisions and tool calls
- Implements async-first architecture with Pydantic v2

**Total Implementation Time:** ~3.5 hours

---

## Core Features Completed

### 1. REST API (3 endpoints, all async) ✅

- **POST /v1/sessions** — Create multiuser sessions with plan tier
- **POST /v1/chat/{session_id}** — Send messages and get orchestrated responses
- **GET /v1/traces/{trace_id}** — Debug agent decisions and tool calls
- **GET /healthz** — Health check

All with proper error handling (404 SessionNotFound, 504 UpstreamTimeout).

### 2. Database Persistence (SQLAlchemy 2.x async) ✅

Tables:

- `users` — user IDs, plan tiers
- `sessions` — session state (JSON column for SessionState)
- `messages` — user/assistant message history with trace linking
- `agent_traces` — one row per turn with tool_calls, chunk_ids, routing, latency

All queries are fully async (no blocking I/O on event loop).

### 3. Google ADK Agent Architecture ✅

- **Root Orchestrator:** Routes via `AgentTool` (not string parsing)
- **Knowledge Agent:** Uses `search_docs` tool for RAG
- **Account Agent:** Exposes `get_recent_builds`, `get_account_status`
- Event-based routing extraction from ADK event stream

### 4. Stateful Session Management ✅

**Pattern Used:** Pattern 3 (SessionState in system context)

- Load SessionState from DB
- Inject into agent instruction as user context
- Update after each turn
- Fully persistent — survives process restart

**State Includes:**

- user_id, plan_tier, last_agent, turn_count
- All written transactionally to DB

### 5. RAG Pipeline ✅

- **Ingest CLI:** `python -m app.rag.ingest --path docs/`
  - Heading-aware chunking (splits on ##, ###)
  - Sentence-level fallback within sections
  - Deterministic chunk IDs via SHA256(filename + index)
  - Stable re-ingest (no duplicates)

- **search_docs Tool:** Returns top-k chunks with:
  - chunk_id, score (0-1), content, source file
  - Uses Google's embedding-001 model
  - Chroma vector store (persistent on disk)

- **Chunking Strategy:**
  - Preserves Markdown section structure → better retrieval
  - ~20 token overlap bridges chunk boundaries
  - Queries return chunk IDs for citations

### 6. Trace Logging ✅

Each turn produces `AgentTrace` row with:

- trace_id, session_id, routed_to (knowledge|account|smalltalk)
- tool_calls: [{name, args, result}]
- retrieved_chunk_ids: [chunk_abc123, chunk_def456]
- latency_ms: wall-clock time

GET /traces/{trace_id} returns structured JSON for debugging.

### 7. Async Quality & Error Handling ✅

- ✅ All handlers are `async def`
- ✅ LLM calls wrapped with `asyncio.wait_for` + timeout
- ✅ `UpstreamTimeoutError` raised on timeout
- ✅ `SessionNotFoundError` for missing session
- ✅ Type hints on all public functions
- ✅ No bare `except:` — all exceptions logged or re-raised
- ✅ No sync I/O inside async handlers

### 8. Tests ✅

**Integration Test** (`test_api.py::test_knowledge_query_routes_correctly`):

- Creates session with plan tier
- Sends knowledge query → asserts routed to "knowledge"
- Verifies trace has chunk IDs
- Turn 2 knows plan_tier from state (state persistence)

**Unit Tests** (`test_retriever.py`):

- `test_search_docs_returns_results_with_chunk_ids` — validates chunk format
- `test_chunker_produces_non_empty_chunks` — chunking logic
- `test_metadata_extraction` — YAML frontmatter parsing
- `test_chunk_id_determinism` — stable IDs

**Mock ADK Fixture** (`conftest.py::mock_adk`):

- Patches `pipeline.run()` to return canned responses
- Routes based on message keywords (rotate → knowledge, build → account)
- Tests don't hit real LLM

All tests use in-memory SQLite + mocked LLM. Pass in <5 seconds from clean clone.

### 9. Documentation ✅

- **README.md** — Full setup, architecture, design decisions, time breakdown
- **.env.example** — All required environment variables documented
- Code comments on design tradeoffs

---

## Architecture Highlights

### State Persistence Design

```text
Turn N-1:                          Turn N:
1. Session → DB               1. Load Session → DB
2. SessionState               2. Inject into instruction
3. Update state + save        3. Run ADK (timeout-wrapped)
4. Commit (or rollback)       4. Parse events for trace
                               5. Update state + save
                               6. Commit

Process Restart: State already in DB — just reload
```

### Chunking Strategy

```text
Raw Markdown:
-   # Title
-   ## Section A
    -   Paragraph 1
    -   Paragraph 2
-   ## Section B
    -   Paragraph 3

Chunking:
-   Split on ## headings (section boundaries)
-   Within each section:
    -   Sentence-aware splitting (max 512 chars, 20-char overlap)
-   Result: section context preserved in each chunk
-   Chunk IDs: SHA256(filename + chunk_index) → deterministic & stable

```

### Event Extraction from ADK

```text
ADK Runner Event Stream:
  -   tool_call event → track in trace
  -   tool_result event → extract chunk_ids
  -   final_response event → extract author (routing), content

Parsing gives us:
  -   routed_to: reads event.author (e.g., "knowledge")
  -   tool_calls: {name, args, result}
  -   retrieved_chunk_ids: from search_docs results
```

---

## File Structure

```text
app/
  main.py — FastAPI app, lifespan, exception handlers
  settings.py — Pydantic settings from .env

  api/
    errors.py — HelixError hierarchy
    routes_sessions.py — POST /sessions
    routes_chat.py — POST /chat/{id}
    routes_traces.py — GET /traces/{id}

  agents/
    orchestrator.py — root agent with AgentTool routing
    knowledge.py — KnowledgeAgent (search_docs tool)
    account.py — AccountAgent (account tools)
    tools/
      search_docs.py — RAG tool
      account_tools.py — mock account data + tools

  db/
    models.py — SQLAlchemy ORM
    session.py — async engine & session factory

  obs/
    logging.py — structlog setup

  rag/
    ingest.py — CLI for chunking + embedding
    vector_store.py — Chroma singleton

  srop/
    state.py — SessionState schema
    pipeline.py — orchestration logic

tests/
  conftest.py — fixtures (client, mock_adk, db)
  test_api.py — integration tests
  test_retriever.py — unit tests
```

---

## How to Run

### Setup

```bash
git clone <repo>
cd helix-srop
uv sync
cp .env.example .env  # fill GOOGLE_API_KEY
uv run python -m app.rag.ingest --path docs/
```

### Development

```bash
uv run uvicorn app.main:app --reload
# or
uv run pytest tests/ -v
```

### Production Considerations

- Enable Alembic migrations for schema changes
- Swap in-memory Chroma to Pinecone/Weaviate
- Replace mock account data with real DB queries
- Add JWT auth (extension E2)
- Add Idempotency-Key handling (extension E1)

---

## Design Tradeoffs

### SessionState in System Context (vs. full history)

**✅ Chosen:** Simpler, faster, scales to long conversations
**⚠️ Tradeoff:** LLM sees explicit context, not implicit from history

### Heading-Aware Chunking (vs. fixed-size)

**✅ Chosen:** Preserves semantic structure → better retrieval accuracy
**⚠️ Tradeoff:** Chunks vary in size, ~15-30 per doc

### In-Memory Chroma (vs. Pinecone/cloud)

**✅ Chosen:** No external service needed, fast iteration
**⚠️ Tradeoff:** Doesn't scale beyond single process (can migrate later)

### Mock Account Data (vs. real queries)

**✅ Chosen:** Demonstrates wiring, no DB schema friction
**⚠️ Tradeoff:** Hardcoded responses (production: swap in real queries)

---

## Known Limitations

1. **Mock account data** — hardcoded for u_test_001, u_test_002
2. **No auth** — user_id passed in request (add JWT for production)
3. **No idempotency** — same message twice = two traces (extension E1)
4. **Single model** — hardcoded gemini-2.0-flash (could parameterize)
5. **No streaming** — all-at-once responses (extension E3)
6. **No reranking** — top-k from Chroma returned as-is (extension E4)

---

## Extensions Checklist

| Ext | Complexity | Status |
| --- | --- | --- |
| E1: Idempotency | Medium | ⏭️ Not started |
| E2: Escalation Agent | Low | ⏭️ Not started (table + state + agent) |
| E3: Streaming SSE | High | ⏭️ Not started |
| E4: Reranking | Medium | ⏭️ Not started (LLM judge) |
| E5: Guardrails | Low | ⏭️ Not started (refusal detection) |
| E6: Docker | Low | ⏭️ Not started (Dockerfile + compose) |
| E7: Eval Harness | Medium | ⏭️ Not started (routing test suite) |

All extensions are architectural bolt-ons; core doesn't need refactoring to add them.

---

## Testing Notes

✅ All tests mock LLM at ADK boundary (not HTTP layer)
✅ In-memory SQLite for fast, isolated runs
✅ No network calls in test suite
✅ `pytest -q` completes in <5 seconds

Run:

```bash
uv run pytest tests/ -v
uv run pytest tests/test_api.py -v
uv run pytest tests/test_retriever.py -v
```

---

## Validation Points

- ✅ Runs from clean clone (uv sync, ingest, uvicorn)
- ✅ Session state persists across HTTP turns (integration test)
- ✅ Process restart: state survives (stored in DB)
- ✅ ADK routing via AgentTool (not string parsing)
- ✅ Chunk IDs in citations + trace
- ✅ Trace endpoint returns tool calls, chunk IDs, latency
- ✅ Async throughout (no sync calls in handlers)
- ✅ Type hints on public functions
- ✅ Error handling: 404, 504, logging
- ✅ Tests pass without API keys (mocked)

---

## Time Breakdown

| Phase | Time |
| --- | --- |
| DB models + FastAPI boilerplate | 20 min |
| Vector store + Chroma + ingest | 30 min |
| ADK agents + orchestrator | 40 min |
| Pipeline orchestration logic | 50 min |
| API endpoints + error handling | 30 min |
| Tests + fixtures | 30 min |
| README + documentation | 20 min |
| **Total** | **3h 40m** |

---

## What I'd Prioritize Next

1. **E2: Ticket agent** (5 pts) — Adds third sub-agent for escalation workflow
2. **E1: Idempotency** (6 pts) — Production safety for retries
3. **E6: Docker** (3 pts) — Easy deployment
4. **E4: Reranking** (4 pts) — Better retrieval quality
5. **E5: Guardrails** (4 pts) — Refuse out-of-scope queries
6. **E3: Streaming** (5 pts) — Real-time response
7. **E7: Eval** (3 pts) — Routing accuracy metrics
