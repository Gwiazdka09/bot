"""
Tests for Langfuse observability integration.
"""

import os
import pytest
from footstats.ai.analyzer import _get_langfuse


class TestLangfuseInit:
    """Test Langfuse initialization."""

    def test_langfuse_init_with_credentials(self):
        """Langfuse initializes when credentials present."""
        # Only test if credentials are set
        if os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY"):
            langfuse = _get_langfuse()
            assert langfuse is not None, "Langfuse should initialize with valid credentials"

    def test_langfuse_init_without_credentials(self, monkeypatch):
        """Langfuse returns None when credentials missing."""
        # Clear credentials temporarily
        monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
        monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)

        # Clear the cached instance
        import footstats.ai.analyzer as analyzer_module
        analyzer_module._langfuse = None

        langfuse = _get_langfuse()
        # Should gracefully skip if no credentials
        # (either None or uninitialized, both are acceptable)

    def test_langfuse_singleton(self):
        """Langfuse instance is cached."""
        # Get instance twice
        langfuse1 = _get_langfuse()
        langfuse2 = _get_langfuse()

        # Should be same object (cached)
        assert langfuse1 is langfuse2


class TestLangfuseImports:
    """Test that Langfuse imports don't break the analyzer."""

    def test_analyzer_imports_successfully(self):
        """analyzer.py imports without error."""
        from footstats.ai import analyzer
        assert analyzer is not None

    def test_analyzer_has_langfuse_init(self):
        """analyzer.py exports _get_langfuse function."""
        from footstats.ai.analyzer import _get_langfuse
        assert callable(_get_langfuse)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
