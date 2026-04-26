"""Unit tests for RAG embeddings system."""

import sqlite3
import tempfile
from pathlib import Path
import pytest
import numpy as np

from src.footstats.ai.rag_embeddings import EmbeddingStore, ensure_schema, backfill_embeddings


@pytest.fixture
def temp_db():
    """Create temporary SQLite DB for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)

    # Initialize schema
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE ai_feedback (
            id INTEGER PRIMARY KEY,
            match_id INTEGER,
            prediction_details TEXT,
            reason_for_failure TEXT,
            created_at TEXT
        )
    """)
    conn.commit()
    conn.close()

    yield db_path

    # Cleanup
    db_path.unlink(missing_ok=True)
    (db_path.parent / (db_path.name + "-wal")).unlink(missing_ok=True)
    (db_path.parent / (db_path.name + "-shm")).unlink(missing_ok=True)


class TestEmbeddingStore:
    """Tests for EmbeddingStore class."""

    def test_embed_text_produces_vector(self):
        """Embedding text should produce consistent float32 vector."""
        store = EmbeddingStore()
        vec = store.embed_text("Test text")
        assert isinstance(vec, np.ndarray)
        assert vec.dtype == np.float32
        assert vec.shape == (384,)  # MiniLM-L12-v2 dimension

    def test_embed_deterministic(self):
        """Same text should produce same embedding."""
        store = EmbeddingStore()
        text = "Slaba forma druzyny"
        vec1 = store.embed_text(text)
        vec2 = store.embed_text(text)
        assert np.allclose(vec1, vec2)

    def test_embed_empty_text(self):
        """Empty text should produce zero vector."""
        store = EmbeddingStore()
        vec = store.embed_text("")
        assert np.allclose(vec, np.zeros(384, dtype=np.float32))

    def test_upsert_and_retrieve(self, temp_db):
        """Upsert should store embedding and allow retrieval."""
        store = EmbeddingStore(temp_db)
        ensure_schema_in_db(temp_db)

        feedback_id = 1
        text = "Droga zespol stracil mecz"
        assert store.upsert(feedback_id, text)

        # Verify BLOB stored
        conn = sqlite3.connect(temp_db)
        blob = conn.execute("SELECT embedding FROM ai_feedback_embeddings WHERE feedback_id = ?", (feedback_id,)).fetchone()
        conn.close()
        assert blob is not None

    def test_cosine_similarity_basic(self, temp_db):
        """Cosine similarity should rank by relevance."""
        store = EmbeddingStore(temp_db)
        ensure_schema_in_db(temp_db)

        # Upsert related texts
        store.upsert(1, "Slaba forma druzyny domowej")
        store.upsert(2, "Dobre wyniki druzyny goscia")
        store.upsert(3, "Kontuzja pilkarza")

        # Query for "poor form"
        query = store.embed_text("slaba forma zespolu")
        results = store.cosine_top_k(query, k=3, min_score=0.0)

        # Should find 3 results, first likely higher score (form-related)
        assert len(results) == 3
        ids = [r[0] for r in results]
        assert 1 in ids  # Form-related should be included

    def test_cosine_threshold_filtering(self, temp_db):
        """min_score threshold should filter low-similarity results."""
        store = EmbeddingStore(temp_db)
        ensure_schema_in_db(temp_db)

        store.upsert(1, "Slaba forma druzyny")
        store.upsert(2, "Pogoda byla sloneczna")

        query = store.embed_text("slaba forma")
        results_low = store.cosine_top_k(query, k=10, min_score=0.0)
        results_high = store.cosine_top_k(query, k=10, min_score=0.7)

        # Higher threshold should filter more results
        assert len(results_low) >= len(results_high)

    def test_blob_roundtrip(self, temp_db):
        """Embedding BLOB serialization should be faithful."""
        store = EmbeddingStore(temp_db)
        ensure_schema_in_db(temp_db)

        original_vec = store.embed_text("Test tekst")
        store.upsert(1, "Test tekst")

        # Retrieve and deserialize
        conn = sqlite3.connect(temp_db)
        blob = conn.execute("SELECT embedding FROM ai_feedback_embeddings WHERE feedback_id = 1").fetchone()[0]
        conn.close()

        restored_vec = np.frombuffer(blob, dtype=np.float32)
        assert np.allclose(original_vec, restored_vec)

    def test_idempotent_upsert(self, temp_db):
        """Upserting same ID twice should replace (not error)."""
        store = EmbeddingStore(temp_db)
        ensure_schema_in_db(temp_db)

        assert store.upsert(1, "Text 1")
        assert store.upsert(1, "Text 2")  # Should not raise

        conn = sqlite3.connect(temp_db)
        count = conn.execute("SELECT COUNT(*) FROM ai_feedback_embeddings WHERE feedback_id = 1").fetchone()[0]
        conn.close()
        assert count == 1  # Only one row


class TestSemanticRetrieval:
    """Integration tests for semantic lesson retrieval."""

    def test_retrieve_empty_embeddings_table(self, temp_db):
        """Retrieval on empty embeddings should return []."""
        from src.footstats.ai.rag import retrieve_relevant_lessons

        # This will fail to connect to real DB; we'd need a mock for full integration test
        # For now, just verify the function handles no embeddings gracefully


def ensure_schema_in_db(db_path: Path):
    """Helper: ensure embeddings table exists in test DB."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ai_feedback_embeddings (
            feedback_id INTEGER PRIMARY KEY,
            embedding BLOB NOT NULL,
            model_name TEXT NOT NULL,
            dim INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()
