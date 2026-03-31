"""Unit tests for tools/project_discovery.py module."""

import json
from unittest.mock import patch

import pytest

from tests.conftest import *  # noqa: F401, F403


@pytest.mark.unit
class TestProjectDiscovery:
    """Test project discovery functionality."""

    def test_detect_python_with_mock_files(self, mock_project_files):
        """Test Python project detection."""
        from tools.project_discovery import _detect_python_framework

        with patch("tools.project_discovery._get_project_root", return_value=str(mock_project_files)):
            framework = _detect_python_framework(str(mock_project_files))
            # Project has no Flask/FastAPI imports, should return None
            assert framework is None

    def test_detect_django(self, temp_project_dir):
        """Test Django project detection."""
        from tools.project_discovery import _detect_python_framework
        from pathlib import Path

        # Create manage.py which indicates Django
        (Path(temp_project_dir) / "manage.py").write_text("#!/usr/bin/env python\n")

        framework = _detect_python_framework(temp_project_dir)
        assert framework == "Django"

    def test_detect_fastapi(self, temp_project_dir):
        """Test FastAPI project detection."""
        from tools.project_discovery import _detect_python_framework
        from pathlib import Path

        # Create app.py with FastAPI import
        (Path(temp_project_dir) / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")

        framework = _detect_python_framework(temp_project_dir)
        assert framework == "FastAPI"

    def test_detect_flask(self, temp_project_dir):
        """Test Flask project detection."""
        from tools.project_discovery import _detect_python_framework
        from pathlib import Path

        # Create main.py with Flask import
        (Path(temp_project_dir) / "main.py").write_text("from flask import Flask\napp = Flask(__name__)\n")

        framework = _detect_python_framework(temp_project_dir)
        assert framework == "Flask"

    def test_detect_data_files(self, mock_project_files):
        """Test data file detection."""
        from tools.project_discovery import _detect_data_files

        result = _detect_data_files(str(mock_project_files))
        assert result["found"] is True
        assert result["counts"]["csv"] >= 1
        assert result["counts"]["json_data"] >= 0

    def test_count_files(self, mock_project_files):
        """Test file counting."""
        from tools.project_discovery import _count_files

        # Count Python files
        count = _count_files(str(mock_project_files), ".py")
        assert count >= 2  # main.py and config.py

    def test_find_file(self, mock_project_files):
        """Test finding files in directory."""
        from tools.project_discovery import _find_file

        # Find existing file
        found_dir = _find_file(str(mock_project_files), "dbt_project.yml")
        assert found_dir is not None

        # Try to find non-existent file
        not_found = _find_file(str(mock_project_files), "nonexistent.txt")
        assert not_found is None
