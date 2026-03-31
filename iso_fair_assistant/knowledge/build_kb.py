"""
build_kb.py  —  Scrape Ostfalia pages and build the RAG knowledge base.

Run this ONCE before the fair (needs internet). Saves everything locally.
On demo day, no internet required.

Usage:
    pip install requests beautifulsoup4 sentence-transformers chromadb
    python build_kb.py

Output:
    knowledge/raw_texts/*.txt   — cleaned plain text from each page
    knowledge/kb_index/         — ChromaDB embedding index (used at runtime)
"""

import os
import re
import time
import requests
from bs4 import BeautifulSoup

# TODO: CHECK URLS AS SOME ARE IN GERMAN

# ── Pages to scrape ────────────────────────────────────────────────────────────
PAGES = {
    "iso_main":       "https://www.ostfalia.de/hochschule/campus-einrichtungen/international-student-office",
    "incoming":       "https://www.ostfalia.de/hochschule/campus-einrichtungen/international-student-office/incoming-students",
    "fyi":            "https://www.ostfalia.de/en/studieren/im-studium/international/fyi-for-your-integration",
    "wege_ausland":   "https://www.ostfalia.de/studieren/im-studium/international/wege-ins-ausland",
    "sprachen_main":  "https://www.ostfalia.de/hochschule/campus-einrichtungen/sprachenzentrum",
    "daf":            "https://www.ostfalia.de/en/university/campus-facilities/language-centre/german-as-a-foreign-language",
    "daf-courses":    "https://www.ostfalia.de/en/university/campus-facilities/language-centre/german-as-a-foreign-language/german-courses-during-your-studies",
    "tandem":         "https://www.ostfalia.de/en/university/campus-facilities/language-centre/language-tandem",
    "intercultural":  "https://www.ostfalia.de/hochschule/campus-einrichtungen/sprachenzentrum/interkulturelle-angebote",
    "housing":        "https://www.ostfalia.de/studieren/studieninteressierte/wohnen",
    "erasmus":        "https://www.ostfalia.de/hochschule/campus-einrichtungen/international-student-office/outgoing-students/erasmus-programm",
    "stipendien":     "https://www.ostfalia.de/studieren/studieninteressierte/studienfinanzierung",
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; iso-assistant-bot/1.0; research)"}

os.makedirs("knowledge/raw_texts", exist_ok=True)
os.makedirs("knowledge/kb_index", exist_ok=True)


# ── Step 1: Scrape ─────────────────────────────────────────────────────────────

def scrape(url: str) -> str:
    """Fetch a page and return clean plain text."""
    r = requests.get(url, headers=HEADERS, timeout=15)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    # Remove navigation, footer, scripts, styles, cookie banners
    for tag in soup(["nav", "footer", "script", "style", "header", "aside"]):
        tag.decompose()
    for tag in soup.find_all(class_=re.compile(r"cookie|banner|modal|overlay", re.I)):
        tag.decompose()

    # Try to find the main content block
    main = (
        soup.find("main") or
        soup.find("div", {"id": "inhalt"}) or
        soup.find("div", class_=re.compile(r"content|main", re.I)) or
        soup.body
    )

    raw = main.get_text(separator="\n", strip=True) if main else ""

    # Clean up: remove runs of blank lines
    lines = [l.strip() for l in raw.splitlines() if l.strip()]
    return "\n".join(lines)


print("=== Step 1: Scraping pages ===")
scraped = {}
for key, url in PAGES.items():
    try:
        text = scrape(url)
        scraped[key] = text
        path = f"knowledge/raw_texts/{key}.txt"
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"SOURCE: {url}\n\n{text}")
        print(f"  ✓ {key}  ({len(text)} chars)  → {path}")
    except Exception as e:
        print(f"  ✗ {key}: {e}")
    time.sleep(1)   # be polite to the server

# Also copy the manually curated files (already exist from the pre-built set)
# The scraper result and the manual files are merged in Step 2.


# ── Step 2: Chunk ──────────────────────────────────────────────────────────────

def chunk_text(text: str, source: str, chunk_size: int = 400, overlap: int = 80):
    """Split text into overlapping chunks for embedding."""
    words = text.split()
    chunks = []
    i = 0
    chunk_id = 0
    while i < len(words):
        chunk_words = words[i:i + chunk_size]
        chunk_text = " ".join(chunk_words)
        chunks.append({
            "id":     f"{source}_chunk_{chunk_id}",
            "source": source,
            "text":   chunk_text,
        })
        chunk_id += 1
        i += chunk_size - overlap
    return chunks


print("\n=== Step 2: Chunking ===")
all_chunks = []
raw_dir = "knowledge/raw_texts"
for fname in os.listdir(raw_dir):
    if not fname.endswith(".txt"):
        continue
    key = fname.replace(".txt", "")
    with open(os.path.join(raw_dir, fname), encoding="utf-8") as f:
        text = f.read()
    chunks = chunk_text(text, source=key)
    all_chunks.extend(chunks)
    print(f"  {key}: {len(chunks)} chunks")

print(f"\n  Total chunks: {len(all_chunks)}")


# ── Step 3: Embed and store in ChromaDB ───────────────────────────────────────

print("\n=== Step 3: Embedding and indexing ===")
print("  (This may take a minute on first run — downloading the embedding model)")

try:
    import chromadb
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer("all-MiniLM-L6-v2")   # small, fast, good quality
    client = chromadb.PersistentClient(path="knowledge/kb_index")

    # Reset collection if it already exists
    try:
        client.delete_collection("iso_kb")
    except Exception:
        pass
    collection = client.create_collection("iso_kb")

    # Embed and add in batches
    batch_size = 50
    for i in range(0, len(all_chunks), batch_size):
        batch = all_chunks[i:i + batch_size]
        texts     = [c["text"] for c in batch]
        ids       = [c["id"]   for c in batch]
        metadatas = [{"source": c["source"]} for c in batch]
        embeddings = model.encode(texts).tolist()
        collection.add(documents=texts, ids=ids, metadatas=metadatas, embeddings=embeddings)
        print(f"  Indexed chunks {i+1}–{min(i+batch_size, len(all_chunks))}")

    print(f"\n  ✓ Knowledge base ready at knowledge/kb_index/")
    print(f"  ✓ Total documents indexed: {collection.count()}")

except ImportError:
    print("  ⚠ chromadb or sentence-transformers not installed.")
    print("  Run: pip install chromadb sentence-transformers")
    print("  The raw text files are saved — embedding skipped for now.")


# ── Step 4: Quick retrieval test ───────────────────────────────────────────────

print("\n=== Step 4: Retrieval test ===")
try:
    model   # already loaded
    collection  # already loaded

    test_queries = [
        "How do I apply for an Erasmus+ scholarship?",
        "What German language courses are available for international students?",
        "Which partner universities does Ostfalia have in Japan?",
        "What health insurance do I need as an international student?",
    ]

    for q in test_queries:
        q_embedding = model.encode([q]).tolist()
        results = collection.query(query_embeddings=q_embedding, n_results=2)
        top = results["documents"][0][0][:120].replace("\n", " ")
        src = results["metadatas"][0][0]["source"]
        print(f"\n  Q: {q}")
        print(f"  → [{src}] {top}...")

except Exception as e:
    print(f"  Skipped (embedding not available): {e}")

print("\n=== Done. Run main.py to start the assistant. ===")
