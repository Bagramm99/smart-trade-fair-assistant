# knowledge_base.py — runtime RAG search
#
# Loads the pre-built ChromaDB index and exposes search().
# Build the index first with: python embed_knowledge_base.py
import os
import logging
log = logging.getLogger("kb")
# These are the topic keywords the LLM can return so we can map to Temi images.
# Must match the keys in temi_agent.TOPIC_IMAGES.
KNOWN_TOPICS = [
    "erasmus", "partner_universities", "studying_abroad", "outgoing_process",
    "europe_partners", "new_erasmus_partners", "non_eu_partners", "americas_asia",
    "language_courses", "housing", "health_insurance", "redirect", "welcome", "farewell",
]
# TODO: Need to add new known topics accordingly to all the ones that we have.
class KnowledgeBase:
    def __init__(self, index_dir: str = "knowledge/kb_index", embed_model: str = "all-MiniLM-L6-v2", top_k: int = 3):
        self._top_k = top_k
        self._ready = False
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer
            self._model       = SentenceTransformer(embed_model)
            self._client      = chromadb.PersistentClient(path=index_dir)
            self._collection = self._client.get_collection("iso_knowledge")
            self._ready = True
            log.info("Knowledge base loaded (%d chunks).", self._collection.count())
        except Exception as e:
            log.warning("Knowledge base not available: %s", e)
            log.warning("Run embed_knowledge_base.py first to build the index.")
    def search(self, query: str) -> str:
        """
        Return the top-k most relevant knowledge chunks as a single string,
        ready to be injected into the LLM system prompt as context.
        """
        if not self._ready:
            return "(Knowledge base not loaded — answer from general knowledge.)"
        embedding = self._model.encode([query]).tolist()
        results   = self._collection.query(
            query_embeddings=embedding,
            n_results=self._top_k,
        )
        chunks = results["documents"][0]
        metas  = results["metadatas"][0]
        parts = []
        for chunk, meta in zip(chunks, metas):
            parts.append(f"[{meta.get('topic', 'ISO info')}]\n{chunk}")
        return "\n\n".join(parts)
    @property
    def ready(self) -> bool:
        return self._ready