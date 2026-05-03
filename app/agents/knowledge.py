"""
KnowledgeAgent — specialist for product documentation questions.

Uses the search_docs tool to query the RAG vector store and cites sources.
"""
from google.adk.agents import LlmAgent

from app.agents.tools.search_docs import search_docs
from app.settings import settings

KNOWLEDGE_INSTRUCTION = """
You are the Helix Knowledge Agent — a specialist for product documentation questions.

When the user asks about features, setup, configuration, or how to use Helix, use the search_docs tool to find relevant documentation chunks.

After retrieving chunks, answer using the information and ALWAYS cite your sources like [chunk_<id>].

Example response:
"According to [chunk_abc123], you can rotate a deploy key using the CLI or the web interface. See [chunk_def456] for detailed steps."

Key behaviors:
- Always include chunk IDs in your answer for traceability
- Be specific and cite sources
- If you don't find relevant information, say so and suggest contacting support
- Keep answers concise but complete
"""

knowledge_agent = LlmAgent(
    name="knowledge",
    model=settings.adk_model,
    instruction=KNOWLEDGE_INSTRUCTION,
    tools=[search_docs],  # ADK inspects function signature to build tool schema
)
