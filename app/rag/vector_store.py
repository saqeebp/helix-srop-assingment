"""
Vector store singleton using Chroma for RAG document storage and retrieval.

Chroma provides:
- In-memory + persistent storage (configurable)
- Embedding via OpenAI API or local embeddings
- Metadata filtering
- Cosine similarity search
"""
import hashlib
from typing import Optional

import chromadb

from app.settings import settings


class VectorStoreClient:
    """Singleton wrapper around Chroma client."""

    _instance: Optional["VectorStoreClient"] = None
    _client = None
    _collection = None

    def __new__(cls) -> "VectorStoreClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._client is None:
            # Chroma persistent storage using new API
            self._client = chromadb.PersistentClient(
                path=settings.chroma_persist_dir
            )
            # Get or create the collection for docs
            self._collection = self._client.get_or_create_collection(
                name="helix_docs",
                metadata={"hnsw:space": "cosine"},
            )

    def get_collection(self):
        """Return the Chroma collection."""
        return self._collection

    def upsert_chunks(
        self,
        chunks: list[str],
        chunk_ids: list[str],
        metadatas: list[dict],
        embeddings: list[list[float]],
    ) -> None:
        """
        Add or update chunks in the vector store.

        Args:
            chunks: list of chunk texts
            chunk_ids: list of unique chunk IDs
            metadatas: list of metadata dicts
            embeddings: list of embedding vectors
        """
        self._collection.upsert(
            ids=chunk_ids,
            documents=chunks,
            embeddings=embeddings,
            metadatas=metadatas,
        )

    def search(self, query_embedding: list[float], k: int = 5) -> dict:
        """
        Search for top-k similar chunks.

        Args:
            query_embedding: embedding vector of the query
            k: number of results to return

        Returns:
            dict with keys:
                - ids: list of chunk IDs
                - distances: list of distances (0=identical, 1=opposite)
                - documents: list of chunk texts
                - metadatas: list of metadata dicts
        """
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=k,
        )
        return results

    def get_by_ids(self, chunk_ids: list[str]) -> dict:
        """Retrieve chunks by their IDs."""
        return self._collection.get(ids=chunk_ids)


def get_vector_store() -> VectorStoreClient:
    """Get the global vector store instance."""
    return VectorStoreClient()


def generate_chunk_id(file_path: str, chunk_index: int) -> str:
    """
    Generate a deterministic, stable chunk ID.

    This ensures re-ingesting the same file produces the same chunk IDs,
    allowing Chroma's upsert to deduplicate.

    Args:
        file_path: the source markdown file path
        chunk_index: 0-indexed chunk number within the file

    Returns:
        A stable, short (~12 chars) chunk ID
    """
    content = f"{file_path}#chunk_{chunk_index}"
    hash_hex = hashlib.sha256(content.encode()).hexdigest()[:12]
    return hash_hex
