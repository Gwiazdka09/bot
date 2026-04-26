"""RAG Embeddings: sentence-transformers + SQLite BLOB storage for semantic lesson retrieval."""

import sqlite3
import logging
import numpy as np
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = None  # Lazy-loaded singleton


def _get_embedding_model():
    """Lazy-load sentence-transformers model (cold start ~2s on CPU)."""
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            _EMBEDDING_MODEL = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
            logger.info("[RAG] Embedding model loaded (multilingual MiniLM)")
        except ImportError:
            logger.error("[RAG] sentence-transformers not installed. Install via: pip install sentence-transformers")
            raise
    return _EMBEDDING_MODEL


def _get_db_path() -> Path:
    """Get footstats_backtest.db path."""
    return Path(__file__).parent.parent.parent.parent / "data" / "footstats_backtest.db"


def ensure_schema():
    """Create ai_feedback_embeddings table if not exists."""
    db_path = _get_db_path()
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS ai_feedback_embeddings (
            feedback_id INTEGER PRIMARY KEY,
            embedding BLOB NOT NULL,
            model_name TEXT NOT NULL,
            dim INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(feedback_id) REFERENCES ai_feedback(id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()
    logger.info("[RAG] Embeddings table schema ensured")


class EmbeddingStore:
    """Encapsulates embedding generation, storage, and retrieval."""

    def __init__(self, db_path: Optional[Path] = None, model_name: str = "paraphrase-multilingual-MiniLM-L12-v2"):
        self.db_path = db_path or _get_db_path()
        self.model_name = model_name
        self.model = _get_embedding_model()
        # Use get_embedding_dimension() for newer versions; fallback to old name for compat
        self.dim = getattr(self.model, 'get_embedding_dimension', self.model.get_sentence_embedding_dimension)()

    def embed_text(self, text: str) -> np.ndarray:
        """Generate embedding vector for text. Returns float32 ndarray."""
        if not text or not text.strip():
            return np.zeros(self.dim, dtype=np.float32)
        embedding = self.model.encode(text, convert_to_numpy=True)
        return embedding.astype(np.float32)

    def upsert(self, feedback_id: int, text: str) -> bool:
        """Embed text and upsert into ai_feedback_embeddings. Returns success flag."""
        try:
            embedding = self.embed_text(text)
            blob = embedding.tobytes()

            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("""
                INSERT OR REPLACE INTO ai_feedback_embeddings (feedback_id, embedding, model_name, dim)
                VALUES (?, ?, ?, ?)
            """, (feedback_id, blob, self.model_name, self.dim))
            conn.commit()
            conn.close()
            return True
        except Exception as e:
            logger.error(f"[RAG] Failed to upsert embedding for feedback_id={feedback_id}: {e}")
            return False

    def get_all(self) -> tuple[list[int], Optional[np.ndarray]]:
        """
        Fetch all embeddings. Returns (list of feedback_ids, matrix of embeddings).
        Matrix shape: (num_embeddings, dim). Returns ([], None) if table empty.
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT feedback_id, embedding FROM ai_feedback_embeddings ORDER BY feedback_id")
            rows = cur.fetchall()
            conn.close()

            if not rows:
                return [], None

            ids = [row[0] for row in rows]
            embeddings = np.array([
                np.frombuffer(row[1], dtype=np.float32) for row in rows
            ])
            return ids, embeddings
        except Exception as e:
            logger.error(f"[RAG] Failed to fetch all embeddings: {e}")
            return [], None

    def cosine_top_k(self, query_vec: np.ndarray, k: int = 5, min_score: float = 0.35) -> list[tuple[int, float]]:
        """
        Semantic search: return top-k (feedback_id, cosine_score) by similarity to query_vec.
        Filters by min_score threshold. Returns empty list if not enough matches.
        """
        feedback_ids, embeddings = self.get_all()
        if embeddings is None or len(embeddings) == 0:
            return []

        # Normalize vectors for cosine similarity
        query_normalized = query_vec / (np.linalg.norm(query_vec) + 1e-8)
        embeddings_normalized = embeddings / (np.linalg.norm(embeddings, axis=1, keepdims=True) + 1e-8)

        # Compute cosine similarities
        similarities = embeddings_normalized @ query_normalized

        # Filter by min_score, sort descending, take top-k
        results = [(feedback_ids[i], float(similarities[i])) for i in range(len(feedback_ids)) if similarities[i] >= min_score]
        results.sort(key=lambda x: x[1], reverse=True)
        return results[:k]


def backfill_embeddings(db_path: Optional[Path] = None, verbose: bool = False):
    """
    One-time backfill: embed all ai_feedback rows and upsert into ai_feedback_embeddings.
    Idempotent — safe to re-run for model swaps. Requires ai_feedback table populated.
    """
    ensure_schema()
    store = EmbeddingStore(db_path)

    try:
        conn = sqlite3.connect(store.db_path)
        cur = conn.cursor()
        cur.execute("SELECT id, reason_for_failure FROM ai_feedback WHERE reason_for_failure IS NOT NULL ORDER BY id")
        rows = cur.fetchall()
        conn.close()

        if not rows:
            logger.info("[RAG] No ai_feedback rows to backfill")
            return

        count = 0
        for feedback_id, reason_text in rows:
            if store.upsert(feedback_id, reason_text):
                count += 1
                if verbose and count % 10 == 0:
                    logger.info(f"[RAG] Backfilled {count}/{len(rows)} embeddings")

        logger.info(f"[RAG] Backfill complete: {count}/{len(rows)} embeddings stored")
    except Exception as e:
        logger.error(f"[RAG] Backfill failed: {e}")


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="[%(name)s] %(message)s")

    if "--reindex" in sys.argv:
        db_path_arg = None
        if "--db" in sys.argv:
            idx = sys.argv.index("--db")
            if idx + 1 < len(sys.argv):
                db_path_arg = Path(sys.argv[idx + 1])
        backfill_embeddings(db_path_arg, verbose=True)
    else:
        print("Usage: python -m footstats.ai.rag_embeddings --reindex [--db /path/to/db]")
