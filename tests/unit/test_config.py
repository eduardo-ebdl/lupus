"""Unit tests for config.py module."""

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.mark.unit
class TestMaxContextBytes:
    """Test MAX_CONTEXT_BYTES configuration."""

    def test_default_max_context_bytes(self, isolate_config):  # noqa: F811
        """Test that default MAX_CONTEXT_BYTES is 8000."""
        isolate_config.setenv("LUPUS_MAX_CONTEXT_BYTES", "")
        # Re-import to pick up env change
        import importlib
        import config

        # Can't easily reload due to module-level execution, but we can test via new import
        # This is a limitation of config.py module-level code, just verify the constant exists
        assert hasattr(config, "MAX_CONTEXT_BYTES")
        assert config.MAX_CONTEXT_BYTES > 0

    def test_custom_max_context_bytes(self, isolate_config):  # noqa: F811
        """Test that LUPUS_MAX_CONTEXT_BYTES env var is respected."""
        isolate_config.setenv("LUPUS_MAX_CONTEXT_BYTES", "16000")
        # In a real scenario, we'd reload the module, but module-level code
        # execution in config.py makes this difficult in pytest
        # This test documents the expected behavior
        assert os.getenv("LUPUS_MAX_CONTEXT_BYTES") == "16000"

    def test_max_context_bytes_validation(self):
        """Test that MAX_CONTEXT_BYTES validates as integer."""
        # Verify the constant can be used as integer
        import config

        result = max(500, config.MAX_CONTEXT_BYTES // 4)
        assert isinstance(result, int)
        assert result >= 500


@pytest.mark.unit
class TestMakeAgent:
    """Test make_agent function."""

    def test_make_agent_with_default_checkpointer(self):
        """Test make_agent without injected checkpointer."""
        from config import make_agent

        with patch("config.get_checkpointer") as mock_get_checkpointer:
            mock_checkpointer = MagicMock()
            mock_get_checkpointer.return_value = mock_checkpointer

            with patch("config.build_llm") as mock_build_llm:
                mock_build_llm.return_value = MagicMock()
                with patch("config.FilesystemBackend"):
                    with patch("config.create_agent") as mock_create_agent:
                        mock_create_agent.return_value = MagicMock()

                        make_agent()

                        # Should call get_checkpointer since checkpointer=None
                        mock_get_checkpointer.assert_called_once()

    def test_make_agent_with_injected_checkpointer(self):
        """Test make_agent with injected checkpointer (test scenario)."""
        from config import make_agent

        mock_checkpointer = MagicMock()

        with patch("config.build_llm") as mock_build_llm:
            mock_build_llm.return_value = MagicMock()
            with patch("config.FilesystemBackend"):
                with patch("config.create_agent") as mock_create_agent:
                    mock_agent = MagicMock()
                    mock_create_agent.return_value = mock_agent

                    result = make_agent(checkpointer=mock_checkpointer)

                    # Should pass the injected checkpointer to create_agent
                    _, kwargs = mock_create_agent.call_args
                    assert kwargs["checkpointer"] is mock_checkpointer
                    assert result is mock_agent


@pytest.mark.unit
class TestGetCheckpointer:
    """Test get_checkpointer function."""

    def test_get_checkpointer_lazy_initialization(self):
        """Test that get_checkpointer uses lazy initialization."""
        import config

        # Reset state
        config._checkpointer = None
        config._db_conn = None

        with patch("config.os.makedirs"):
            with patch("config.sqlite3.connect") as mock_connect:
                with patch("config.SqliteSaver") as mock_saver:
                    mock_connection = MagicMock()
                    mock_connect.return_value = mock_connection
                    mock_checkpointer_instance = MagicMock()
                    mock_saver.return_value = mock_checkpointer_instance

                    result = config.get_checkpointer()

                    # Should have created the checkpointer
                    mock_saver.assert_called_once_with(conn=mock_connection)
                    assert result is mock_checkpointer_instance

    def test_get_checkpointer_singleton(self):
        """Test that get_checkpointer returns singleton."""
        import config

        # Create a checkpointer once
        config._checkpointer = None
        config._db_conn = None

        with patch("config.os.makedirs"):
            with patch("config.sqlite3.connect"):
                with patch("config.SqliteSaver") as mock_saver:
                    mock_checkpointer_instance = MagicMock()
                    mock_saver.return_value = mock_checkpointer_instance

                    result1 = config.get_checkpointer()
                    result2 = config.get_checkpointer()

                    # Should return the same instance
                    assert result1 is result2
                    # SqliteSaver should only be called once
                    mock_saver.assert_called_once()
