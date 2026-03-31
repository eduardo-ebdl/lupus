"""Pytest fixtures and configuration for Lupus tests."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def temp_project_dir():
    """Create a temporary directory for mock repository testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield tmpdir


@pytest.fixture
def mock_project_files(temp_project_dir):
    """Create mock project files in temp directory."""
    project_root = Path(temp_project_dir)

    # Create Python files
    (project_root / "main.py").write_text("def main():\n    pass\n")
    (project_root / "config.py").write_text("API_KEY = 'secret'\n")

    # Create dbt files
    (project_root / "dbt_project.yml").write_text("name: 'test_project'\n")
    (project_root / "models").mkdir()
    (project_root / "models" / "staging.sql").write_text("SELECT * FROM raw_data\n")

    # Create data files
    (project_root / "data").mkdir()
    (project_root / "data" / "test.csv").write_text("id,name\n1,test\n")
    (project_root / "data" / "test.json").write_text('{"key": "value"}')

    # Create README
    (project_root / "README.md").write_text("# Test Project\n")

    return project_root


@pytest.fixture
def mock_ctx_manager(temp_project_dir):
    """Create a mock context manager pointing to temp directory."""
    mock = MagicMock()
    mock.path = temp_project_dir
    mock.name = "test_project"
    mock.context = MagicMock()
    mock.context.path = temp_project_dir
    mock.repo_change_count = 0
    return mock


@pytest.fixture
def mock_checkpointer():
    """Create a mock checkpointer for testing (avoids SQLite I/O)."""
    mock = MagicMock()
    mock.invoke = MagicMock(return_value={})
    mock.get_state = MagicMock(return_value={})
    return mock


@pytest.fixture
def isolate_config(monkeypatch):
    """Isolate config module from file system during tests."""
    # Mock the ctx_manager.init_from_env to prevent side effects
    def mock_init(*args, **kwargs):
        pass

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key-12345")
    monkeypatch.setenv("LUPUS_MAX_CONTEXT_BYTES", "8000")

    return monkeypatch
