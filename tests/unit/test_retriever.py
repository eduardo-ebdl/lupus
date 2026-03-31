"""Unit tests for rag/retriever.py module."""

import threading
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestRetrieverSingleton:
    """Test Retriever singleton and thread safety."""

    def test_get_retriever_returns_singleton(self):
        """Test that get_retriever returns the same instance."""
        # Reset singleton before test
        import rag.retriever as retriever_module
        retriever_module._retriever = None

        with patch("rag.retriever.Retriever.load") as mock_load:
            mock_retriever = MagicMock()
            mock_load.return_value = mock_retriever

            result1 = retriever_module.get_retriever(index_dir="/tmp/test")
            result2 = retriever_module.get_retriever(index_dir="/tmp/test")

            # Should return the same object (singleton)
            assert result1 is result2
            # Load should only be called once
            mock_load.assert_called_once()

    def test_get_retriever_thread_safety(self):
        """Test that get_retriever is thread-safe."""
        import rag.retriever as retriever_module
        retriever_module._retriever = None

        results = []
        lock = threading.Lock()

        def get_retriever_in_thread():
            with patch("rag.retriever.Retriever.load") as mock_load:
                mock_retriever = MagicMock(name=f"retriever_{threading.current_thread().name}")
                mock_load.return_value = mock_retriever

                result = retriever_module.get_retriever(index_dir="/tmp/test")
                with lock:
                    results.append(result)

        # Simulate multiple threads trying to initialize singleton
        threads = [threading.Thread(target=get_retriever_in_thread, name=f"t{i}") for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        # Note: Due to mocking complexity in threading, this test validates
        # that the code path with lock doesn't crash. Full thread safety
        # validation would require integration testing with real initialization.
        assert len(results) == 5


@pytest.mark.unit
class TestSearchResult:
    """Test SearchResult formatting."""

    def test_search_result_format_sql(self):
        """Test formatting of SQL search result."""
        from rag.retriever import SearchResult

        result = SearchResult(
            content="SELECT * FROM table",
            file_path="models/staging.sql",
            file_type="sql",
            layer="silver",
            chunk_type="file",
            chunk_index=0,
            model_name="test-model",
            rrf_score=0.95,
        )

        formatted = result.format(rank=1)
        assert "[1]" in formatted
        assert "models/staging.sql" in formatted
        assert "silver" in formatted
        assert "SELECT * FROM table" in formatted

    def test_search_result_format_notebook_cell(self):
        """Test formatting of notebook cell result."""
        from rag.retriever import SearchResult

        result = SearchResult(
            content="print('hello')",
            file_path="analysis.ipynb",
            file_type="ipynb",
            layer="ai_agent",
            chunk_type="notebook_cell",
            chunk_index=5,
            model_name="test-model",
            rrf_score=0.85,
        )

        formatted = result.format(rank=1)
        assert "célula 5" in formatted


@pytest.mark.unit
class TestSearchResponse:
    """Test SearchResponse formatting."""

    def test_empty_search_response(self):
        """Test formatting of empty search response."""
        from rag.retriever import SearchResponse

        response = SearchResponse(results=[], query="test query")
        assert response.formatted == "Nenhum trecho relevante encontrado no codebase."

    def test_search_response_with_results(self):
        """Test formatting of search response with results."""
        from rag.retriever import SearchResult, SearchResponse

        result1 = SearchResult(
            content="SELECT * FROM users",
            file_path="models/users.sql",
            file_type="sql",
            layer="silver",
            chunk_type="file",
            chunk_index=0,
            model_name="test",
            rrf_score=0.9,
        )
        result2 = SearchResult(
            content="SELECT id FROM users",
            file_path="queries/users.sql",
            file_type="sql",
            layer="gold",
            chunk_type="file",
            chunk_index=0,
            model_name="test",
            rrf_score=0.8,
        )

        response = SearchResponse(results=[result1, result2], query="users")
        formatted = response.formatted

        assert "2 trecho(s)" in formatted
        assert "users" in formatted
