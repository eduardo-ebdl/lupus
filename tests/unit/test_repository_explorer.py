"""Unit tests for tools/repository_explorer.py module."""

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.mark.unit
class TestFileType:
    """Test file type detection."""

    def test_python_file_type(self):
        """Test Python file type detection."""
        from tools.repository_explorer import _file_type

        assert _file_type("test.py") == "python"
        assert _file_type("main.py") == "python"

    def test_sql_file_type(self):
        """Test SQL file type detection."""
        from tools.repository_explorer import _file_type

        assert _file_type("query.sql") == "sql"

    def test_config_file_type(self):
        """Test config file type detection."""
        from tools.repository_explorer import _file_type

        assert _file_type("config.yml") == "config"
        assert _file_type("settings.yaml") == "config"
        assert _file_type("setup.cfg") == "config"

    def test_data_file_type(self):
        """Test data file type detection."""
        from tools.repository_explorer import _file_type

        assert _file_type("data.csv") == "data"
        assert _file_type("dataset.parquet") == "data"

    def test_docker_file_type(self):
        """Test Dockerfile type detection."""
        from tools.repository_explorer import _file_type

        assert _file_type("Dockerfile") == "docker"

    def test_markdown_file_type(self):
        """Test Markdown file type detection."""
        from tools.repository_explorer import _file_type

        assert _file_type("README.md") == "markdown"

    def test_unknown_file_type(self):
        """Test unknown file type detection."""
        from tools.repository_explorer import _file_type

        assert _file_type("file.xyz") == "other"


@pytest.mark.unit
class TestSecretScanning:
    """Test secret scanning in files."""

    def test_no_secrets_in_clean_file(self, temp_project_dir):
        """Test that clean files don't trigger secret warnings."""
        from tools.repository_explorer import _scan_secrets
        from pathlib import Path

        # Create a clean Python file
        py_file = Path(temp_project_dir) / "clean.py"
        py_file.write_text("def hello():\n    print('Hello, world!')\n")

        findings = _scan_secrets(temp_project_dir, [{"path": "clean.py", "type": "python"}])
        assert len(findings) == 0

    def test_detects_hardcoded_password(self, temp_project_dir):
        """Test that hardcoded passwords are detected."""
        from tools.repository_explorer import _scan_secrets
        from pathlib import Path

        # Create a file with hardcoded password
        py_file = Path(temp_project_dir) / "config.py"
        py_file.write_text("PASSWORD = 'supersecret123'\n")

        findings = _scan_secrets(temp_project_dir, [{"path": "config.py", "type": "config"}])
        assert len(findings) > 0
        assert findings[0]["type"] == "password"

    def test_detects_api_key(self, temp_project_dir):
        """Test that API keys are detected."""
        from tools.repository_explorer import _scan_secrets
        from pathlib import Path

        # Create a file with API key
        py_file = Path(temp_project_dir) / "api.py"
        py_file.write_text("API_KEY = 'sk_test_1234567890abcdef'\n")

        findings = _scan_secrets(temp_project_dir, [{"path": "api.py", "type": "python"}])
        assert len(findings) > 0
        assert findings[0]["type"] == "api_key"

    def test_skips_env_example_files(self, temp_project_dir):
        """Test that .env.example files are not scanned."""
        from tools.repository_explorer import _scan_secrets
        from pathlib import Path

        # Create .env.example with secret (should be skipped)
        env_file = Path(temp_project_dir) / ".env.example"
        env_file.write_text("API_KEY = 'example_key_123456789'\n")

        findings = _scan_secrets(temp_project_dir, [{"path": ".env.example", "type": "config"}])
        # Should skip .env.example even though it has a key-like pattern
        assert len(findings) == 0


@pytest.mark.unit
class TestExploreRepository:
    """Test repository exploration."""

    def test_explore_with_mock_files(self, mock_project_files):
        """Test exploration of mock project."""
        from tools.repository_explorer import explore_repository

        with patch("tools.repository_explorer._get_project_root", return_value=str(mock_project_files)):
            import json

            result_json = explore_repository(max_depth=3)
            result = json.loads(result_json)

            assert "project_root" in result
            assert "total_files" in result
            assert "type_summary" in result
            assert "key_files" in result
            assert result["total_files"] > 0

    def test_explore_identifies_key_files(self, mock_project_files):
        """Test that key files are identified."""
        from tools.repository_explorer import explore_repository
        import json

        with patch("tools.repository_explorer._get_project_root", return_value=str(mock_project_files)):
            result_json = explore_repository(max_depth=3)
            result = json.loads(result_json)

            key_files = result["key_files"]
            # Should find README.md and dbt_project.yml which are in _KEY_FILES
            assert any("README" in f for f in key_files)
            assert any("dbt_project" in f for f in key_files)

    def test_explore_max_depth(self, mock_project_files):
        """Test that max_depth parameter limits exploration."""
        from tools.repository_explorer import explore_repository
        import json

        with patch("tools.repository_explorer._get_project_root", return_value=str(mock_project_files)):
            # Explore with max_depth=1 should find fewer directories
            result_json = explore_repository(max_depth=1)
            result = json.loads(result_json)

            # Should not be an error, just limited results
            assert "project_root" in result
            assert isinstance(result["directories"], dict)

    def test_explore_invalid_path(self):
        """Test exploration of non-existent path."""
        from tools.repository_explorer import explore_repository
        import json

        with patch("tools.repository_explorer._get_project_root", return_value="/nonexistent/path"):
            result_json = explore_repository()
            result = json.loads(result_json)

            assert "error" in result
            assert "não encontrado" in result["error"].lower()
