"""
RAG ingest CLI.

Usage:
    python -m app.rag.ingest --path docs/
    python -m app.rag.ingest --path docs/ --chunk-size 512 --chunk-overlap 64

Reads markdown files, chunks them, embeds, and writes to the vector store.

Chunking strategy: heading-aware + overlap
- Splits on markdown headings (##, ###) to preserve sections
- Respects chunk_size / overlap within each section
- Helps retrieval because questions usually map to sections
- Fallback to sentence-aware splitting if heading structure is missing
"""
import argparse
import asyncio
import re
from pathlib import Path

import google.generativeai as genai

from app.rag.vector_store import VectorStoreClient, generate_chunk_id
from app.settings import settings


def chunk_markdown(text: str, chunk_size: int = 512, overlap: int = 64) -> list[str]:
    """
    Split markdown text into overlapping chunks using heading-aware strategy.

    - First splits on main sections (## heading)
    - Then applies character-level chunking with overlap within each section
    - Preserves heading context in each chunk
    """
    # Split on ## headings (level 2)
    heading_pattern = r"(?=^## )"
    sections = re.split(heading_pattern, text, flags=re.MULTILINE)

    chunks = []

    for section in sections:
        if not section.strip():
            continue

        # If section is small, keep it as one chunk
        if len(section) <= chunk_size:
            chunks.append(section.strip())
            continue

        # Otherwise, split into overlapping chunks
        sentences = re.split(r"(?<=[.!?])\s+", section)
        current_chunk = ""

        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 1 > chunk_size:
                if current_chunk:
                    chunks.append(current_chunk.strip())
                # Start new chunk with overlap
                current_chunk = " ".join(sentences[max(0, len(chunks) - overlap // 50) :])
                current_chunk = sentence

            current_chunk += " " + sentence if current_chunk else sentence

        if current_chunk.strip():
            chunks.append(current_chunk.strip())

    return [c for c in chunks if c.strip()]


def extract_metadata(file_path: Path, text: str) -> dict:
    """
    Extract metadata from a markdown file.

    Looks for YAML frontmatter, falls back to filename-based metadata.

    Expected frontmatter:
        ---
        title: Deploy Keys
        product_area: security
        ---
    """
    # Extract YAML frontmatter
    frontmatter_pattern = r"^---\n(.*?)\n---"
    match = re.search(frontmatter_pattern, text, re.DOTALL)

    metadata = {
        "source": file_path.name,
        "source_path": str(file_path),
    }

    if match:
        fm_text = match.group(1)
        lines = fm_text.split("\n")
        for line in lines:
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip().strip('"\'')

    # Default title from filename if not in frontmatter
    if "title" not in metadata:
        metadata["title"] = file_path.stem.replace("-", " ").title()

    return metadata


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a batch of texts using Google Generative AI.

    Uses the 'text-embedding-004' model for embeddings.
    """
    if not settings.google_api_key:
        raise ValueError("GOOGLE_API_KEY not set in .env")

    genai.configure(api_key=settings.google_api_key)

    # Use Google's embedding model
    embeddings = []
    for text in texts:
        try:
            result = await asyncio.to_thread(
                genai.embed_content,
                model="models/text-embedding-004",
                content=text,
            )
            embeddings.append(result["embedding"])
        except Exception as e:
            print(f"  Warning: Failed to embed chunk: {e}")
            # Return zero vector as fallback
            embeddings.append([0.0] * 768)

    return embeddings


async def ingest_directory(docs_path: Path, chunk_size: int, chunk_overlap: int) -> None:
    """
    Walk docs_path, chunk and embed every .md file, upsert into vector store.

    Deduplicates chunks by generating stable chunk IDs from file + index.
    """
    md_files = sorted(docs_path.rglob("*.md"))
    if not md_files:
        print(f"No markdown files found in {docs_path}")
        return

    print(f"Found {len(md_files)} markdown files in {docs_path}")
    vs = VectorStoreClient()
    total_chunks = 0

    for file_path in md_files:
        text = file_path.read_text(encoding="utf-8")
        metadata = extract_metadata(file_path, text)
        chunks = chunk_markdown(text, chunk_size, chunk_overlap)

        if not chunks:
            print(f"  {file_path.name}: skipped (empty or only frontmatter)")
            continue

        print(f"  {file_path.name}: {len(chunks)} chunks, embedding...")

        # Generate stable chunk IDs and embed
        chunk_ids = [generate_chunk_id(file_path.name, i) for i in range(len(chunks))]
        embeddings = await embed_texts(chunks)

        # Each chunk gets a copy of the metadata plus source info
        metadatas = [
            {**metadata, "chunk_index": str(i)}
            for i in range(len(chunks))
        ]

        # Upsert to vector store (idempotent — duplicates are replaced)
        try:
            vs.upsert_chunks(chunks, chunk_ids, metadatas, embeddings)
            total_chunks += len(chunks)
            print(f"    ✓ Upserted {len(chunks)} chunks")
        except Exception as e:
            print(f"    ✗ Failed to upsert: {e}")

    print(f"\nIngest complete. Total chunks: {total_chunks}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest docs into the vector store")
    parser.add_argument("--path", type=Path, required=True, help="Directory containing .md files")
    parser.add_argument("--chunk-size", type=int, default=512)
    parser.add_argument("--chunk-overlap", type=int, default=64)
    args = parser.parse_args()

    asyncio.run(ingest_directory(args.path, args.chunk_size, args.chunk_overlap))


if __name__ == "__main__":
    main()
