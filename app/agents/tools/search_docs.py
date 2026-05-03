"""
search_docs tool — used by KnowledgeAgent.

Queries the vector store for relevant documentation chunks.
Returns chunk IDs, scores, and content so the agent can cite sources.

This tool is called directly by the ADK LlmAgent, which inspects its signature
and docstring to build the tool schema for the LLM.
"""
import asyncio
from dataclasses import dataclass

import google.generativeai as genai

from app.rag.vector_store import VectorStoreClient
from app.settings import settings


@dataclass
class DocChunk:
    chunk_id: str
    score: float
    content: str
    metadata: dict  # e.g. {"product_area": "security", "source": "deploy-keys.md"}


async def search_docs(query: str, k: int = 5) -> dict:
    """
    Search the vector store for top-k relevant documentation chunks.

    Args:
        query: natural language query from the user
        k: number of chunks to return (default 5)

    Returns:
        A dictionary with results key containing list of dicts with:
        - chunk_id: unique chunk identifier
        - score: similarity score [0-1]
        - content: chunk text
        - source: source filename

    The ADK LLM agent will use this to cite sources.
    
    NOTE: Due to embedding model API availability, using mock retrieval
    for MVP. In production, connect to real embedding API.
    """
    # TEMPORARY: Mock retrieval for MVP
    # In production, use real vector store search with proper embedding model
    mock_results = {
        "results": [
            {
                "chunk_id": "chunk_deploy_keys_001",
                "score": 0.92,
                "content": "Deploy keys are SSH keys that grant repository push/pull access. To rotate a deploy key: 1) Generate a new SSH key pair, 2) Add the public key to your Helix configuration, 3) Update your deployment scripts to use the new key, 4) Remove the old key after verification",
                "source": "deploy-keys.md"
            },
            {
                "chunk_id": "chunk_deploy_keys_002",
                "score": 0.85,
                "content": "Security best practices for deploy keys: Always rotate deploy keys every 90 days. Use read-only keys where possible. Monitor key usage through audit logs. Never commit private keys to version control.",
                "source": "deploy-keys.md"
            }
        ]
    }
    
    return mock_results
