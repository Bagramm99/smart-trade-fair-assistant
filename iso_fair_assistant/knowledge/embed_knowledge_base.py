"""
embed_knowledge_base.py
────────────────────────
Reads all .txt files in knowledge/raw_texts/, splits them into chunks,
generates embeddings, and saves a searchable vector index.

Run after build_knowledge_base.py:
    pip install sentence-transformers chromadb
    python embed_knowledge_base.py

Then at runtime, use search_kb(query) to retrieve relevant chunks.
"""

import os
import json
import chromadb
from sentence_transformers import SentenceTransformer

RAW_DIR    = "knowledge/raw_texts"
INDEX_DIR  = "knowledge/kb_index"
MODEL_NAME = "all-MiniLM-L6-v2"   # small, fast, works offline after first download
CHUNK_SIZE = 400    # characters per chunk
CHUNK_OVERLAP = 80  # overlap between chunks to preserve context


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks."""
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        start += size - overlap
    return chunks


def build_index():
    print(f"Loading embedding model: {MODEL_NAME} ...")
    model = SentenceTransformer(MODEL_NAME)

    client = chromadb.PersistentClient(path=INDEX_DIR)

    # Drop and recreate collection for a clean build
    try:
        client.delete_collection("iso_knowledge")
    except Exception:
        pass
    collection = client.create_collection("iso_knowledge")

    all_chunks = []
    all_ids    = []
    all_metas  = []

    txt_files = [f for f in os.listdir(RAW_DIR) if f.endswith(".txt")]
    print(f"Found {len(txt_files)} source files.\n")

    for fname in sorted(txt_files):
        path = os.path.join(RAW_DIR, fname)
        with open(path, encoding="utf-8") as f:
            content = f.read()

        # Parse header
        lines = content.splitlines()
        source = lines[0].replace("SOURCE: ", "").strip() if lines else fname
        topic  = lines[1].replace("TOPIC: ", "").strip() if len(lines) > 1 else ""
        body   = "\n".join(lines[4:]) if len(lines) > 4 else content

        chunks = chunk_text(body)
        print(f"  {fname}: {len(chunks)} chunks")

        for i, chunk in enumerate(chunks):
            chunk_id = f"{fname}_{i}"
            all_chunks.append(chunk)
            all_ids.append(chunk_id)
            all_metas.append({
                "source": source,
                "topic": topic,
                "file": fname,
                "chunk_index": i,
            })

    print(f"\nEmbedding {len(all_chunks)} chunks ...")
    embeddings = model.encode(all_chunks, show_progress_bar=True).tolist()

    collection.add(
        documents=all_chunks,
        embeddings=embeddings,
        ids=all_ids,
        metadatas=all_metas,
    )

    print(f"\nIndex saved to: {INDEX_DIR}")
    print(f"Total chunks indexed: {len(all_chunks)}")


# ── Runtime search function (import this in your orchestrator) ─────────────────

def load_search_fn(top_k: int = 3):
    """
    Returns a search function that retrieves the top-k most relevant chunks
    for a given query string.

    Usage in orchestrator.py:
        from embed_knowledge_base import load_search_fn
        search_kb = load_search_fn()
        chunks = search_kb("How do I apply for Erasmus?")
        context = "\n\n".join(chunks)
    """
    model  = SentenceTransformer(MODEL_NAME)
    client = chromadb.PersistentClient(path=INDEX_DIR)
    collection = client.get_collection("iso_knowledge")

    def search(query: str) -> list[str]:
        embedding = model.encode([query]).tolist()
        results = collection.query(
            query_embeddings=embedding,
            n_results=top_k,
        )
        docs  = results["documents"][0]
        metas = results["metadatas"][0]
        formatted = []
        for doc, meta in zip(docs, metas):
            formatted.append(f"[Source: {meta['topic']}]\n{doc}")
        return formatted

    return search


if __name__ == "__main__":
    build_index()
