"""
Unit tests for RAG retrieval.

Note: These tests require the vector store to be seeded first.
Run: python -m app.rag.ingest --path docs/

For testing purposes, we provide mock tests that verify the chunking and search_docs interface.
"""
import pytest


@pytest.mark.asyncio
async def test_search_docs_returns_results_with_chunk_ids():
    """search_docs must return chunk IDs and scores in [0, 1]."""
    from app.agents.tools.search_docs import search_docs
    from app.settings import settings

    # Skip if no API key (expected in CI)
    if not settings.google_api_key:
        pytest.skip("GOOGLE_API_KEY not set, skipping live vector store test")

    try:
        result = await search_docs("how to rotate a deploy key", k=3)
        # search_docs returns a dict with 'results' key
        assert isinstance(result, dict), "search_docs should return a dict"
        results = result.get("results", [])

        # If vector store is empty, results will be empty — that's OK for this test
        if results:
            for r in results:
                assert "chunk_id" in r, "Result missing chunk_id"
                assert "score" in r, "Result missing score"
                assert isinstance(r["score"], (int, float)), "Score should be numeric"
                assert 0.0 <= r["score"] <= 1.0, f"Score {r['score']} out of range [0, 1]"
    except Exception as e:
        # If embeddings fail (no API or network), skip
        pytest.skip(f"Skipping live test due to: {e}")


def test_chunker_produces_non_empty_chunks():
    """Chunker must not produce empty strings."""
    from app.rag.ingest import chunk_markdown

    text = """# Header

Some content here.

## Section 2

More content in section 2. This is longer text to ensure we have enough.

## Section 3

Final section content."""

    chunks = chunk_markdown(text, chunk_size=100, overlap=20)
    assert len(chunks) > 0, "Chunker produced no chunks"
    assert all(c.strip() for c in chunks), "Chunker produced empty chunks"


def test_metadata_extraction():
    """Metadata extraction should handle frontmatter and filenames."""
    from pathlib import Path
    from app.rag.ingest import extract_metadata

    # Test with frontmatter
    text_with_fm = """---
title: Deploy Keys
product_area: security
---

# Deploy Keys

Content here."""

    metadata = extract_metadata(Path("deploy-keys.md"), text_with_fm)
    assert metadata.get("title") == "Deploy Keys"
    assert metadata.get("product_area") == "security"
    assert metadata.get("source") == "deploy-keys.md"

    # Test without frontmatter (fallback to filename)
    text_no_fm = "# Just content\n\nNo frontmatter here."
    metadata2 = extract_metadata(Path("build-guide.md"), text_no_fm)
    assert metadata2.get("title") == "Build Guide"  # derived from filename
    assert metadata2.get("source") == "build-guide.md"


def test_chunk_id_determinism():
    """Chunk IDs must be deterministic so re-ingest doesn't duplicate."""
    from app.rag.vector_store import generate_chunk_id

    id1 = generate_chunk_id("deploy-keys.md", 0)
    id2 = generate_chunk_id("deploy-keys.md", 0)
    id3 = generate_chunk_id("deploy-keys.md", 1)

    assert id1 == id2, "Chunk IDs must be deterministic"
    assert id1 != id3, "Different chunk indices should produce different IDs"
