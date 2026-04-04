"""
memory_store.py — Long-Term Vector Memory
==========================================
Uses ChromaDB + sentence-transformers for fully local, free embeddings.
Stores successful code patterns (score >= 7) for future context injection.

ChromaDB Collections:
  - successful_patterns: task descriptions + code for similarity search

Neo4j Integration:
  - Creates LearningNode linked to Agent and Task
"""

import os
import json
import uuid
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("memory_store")

CHROMA_HOST = os.getenv("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.getenv("CHROMA_PORT", "8001"))
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # Fast, local, free — 80MB model


class MemoryStore:
    """
    Manages long-term memory using ChromaDB vector store.
    All embeddings are generated locally via sentence-transformers.
    """

    COLLECTION_NAME = "successful_patterns"

    def __init__(self):
        self._client = None
        self._collection = None
        self._embedding_fn = None
        self._initialized = False

    def _ensure_initialized(self):
        """Lazy initialization to avoid startup errors."""
        if self._initialized:
            return

        try:
            self._init_chroma()
            self._initialized = True
        except Exception as e:
            logger.warning(f"ChromaDB initialization failed: {e}. Memory disabled.")

    def _init_chroma(self):
        """Initialize ChromaDB client and embedding function."""
        import chromadb
        from chromadb.utils import embedding_functions

        # Try HTTP client first (for Docker), fallback to in-memory
        try:
            self._client = chromadb.HttpClient(
                host=CHROMA_HOST,
                port=CHROMA_PORT,
            )
            self._client.heartbeat()
            logger.info(f"Connected to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}")
        except Exception as e:
            logger.warning(f"ChromaDB HTTP client failed ({e}), using local persistent storage")
            persist_dir = Path("./chroma_db")
            persist_dir.mkdir(exist_ok=True)
            self._client = chromadb.PersistentClient(path=str(persist_dir))

        # Load sentence-transformers embedding function
        self._embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name=EMBEDDING_MODEL
        )
        logger.info(f"Embedding model loaded: {EMBEDDING_MODEL}")

        # Get or create collection
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            embedding_function=self._embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"Collection '{self.COLLECTION_NAME}' ready "
                    f"(count={self._collection.count()})")

    def store_success(
        self,
        task_description: str,
        code: str,
        score: float,
        task_id: str,
        module_id: str,
    ) -> bool:
        """
        Embed and store a successful code generation (score >= 7).
        Also creates a LearningNode in Neo4j.

        Returns True if stored successfully.
        """
        if score < 7:
            return False

        self._ensure_initialized()
        if not self._initialized:
            return False

        try:
            doc_id = f"pattern_{task_id}_{module_id[:8] if module_id else uuid.uuid4().hex[:8]}"

            # Document = task description + code (for rich embedding)
            document = f"TASK: {task_description}\n\nCODE:\n{code[:2000]}"
            metadata = {
                "task_id": task_id,
                "module_id": module_id,
                "score": score,
                "stored_at": datetime.utcnow().isoformat(),
                "task_description": task_description[:500],
                "code_preview": code[:500],
            }

            self._collection.add(
                ids=[doc_id],
                documents=[document],
                metadatas=[metadata],
            )
            logger.info(f"Stored memory pattern: {doc_id} (score={score})")

            # Store LearningNode in Neo4j
            self._store_learning_node(task_id, module_id, score, task_description)
            return True

        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            return False

    def query_similar(self, query_text: str, n_results: int = 3) -> list[dict]:
        """
        Query ChromaDB for the top-N most similar past successful patterns.

        Returns list of dicts with 'task', 'code', 'score'.
        """
        self._ensure_initialized()
        if not self._initialized:
            return []

        try:
            count = self._collection.count()
            if count == 0:
                return []

            actual_n = min(n_results, count)
            results = self._collection.query(
                query_texts=[query_text],
                n_results=actual_n,
                include=["documents", "metadatas", "distances"],
            )

            patterns = []
            if results and results.get("documents"):
                for doc, meta, dist in zip(
                    results["documents"][0],
                    results["metadatas"][0],
                    results["distances"][0],
                ):
                    # Convert cosine distance to similarity
                    similarity = 1 - dist
                    if similarity > 0.3:  # Only use reasonably similar patterns
                        patterns.append({
                            "task": meta.get("task_description", ""),
                            "code": meta.get("code_preview", ""),
                            "score": meta.get("score", 0),
                            "similarity": round(similarity, 3),
                        })

            logger.debug(f"Memory query returned {len(patterns)} patterns")
            return patterns

        except Exception as e:
            logger.error(f"Memory query failed: {e}")
            return []

    def _store_learning_node(
        self, task_id: str, module_id: str, score: float, task_description: str
    ):
        """Create a LearningNode in Neo4j."""
        try:
            from graph.neo4j_client import create_node, link_nodes, query_graph
            node_id = str(uuid.uuid4())
            create_node("LearningNode", {
                "id": node_id,
                "task_id": task_id,
                "module_id": module_id,
                "pattern_summary": task_description[:200],
                "avg_score": score,
                "use_count": 1,
            })
            link_nodes(node_id, task_id, "PRODUCED_BY")

            # Link to DeveloperAgent
            query_graph(
                "MATCH (a:Agent {name: 'DeveloperAgent'}), (l:LearningNode {id: $lid}) "
                "MERGE (a)-[:LEARNED_FROM]->(l)",
                {"lid": node_id},
            )
        except Exception as e:
            logger.debug(f"LearningNode creation failed (non-critical): {e}")

    def get_stats(self) -> dict:
        """Return memory store statistics."""
        self._ensure_initialized()
        if not self._initialized:
            return {"status": "disabled", "count": 0}
        try:
            return {
                "status": "active",
                "count": self._collection.count(),
                "model": EMBEDDING_MODEL,
            }
        except Exception:
            return {"status": "error", "count": 0}
