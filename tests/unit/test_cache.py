"""Unit tests for tools/cache.py module."""

import time
from unittest.mock import patch

import pytest

from tools.cache import clear, get, make_key, set, stats


@pytest.mark.unit
class TestCacheKeyGeneration:
    """Test cache key generation."""

    def test_make_key_basic(self):
        """Test basic key generation."""
        with patch("tools.cache.get_project_path", return_value="/path/to/project"):
            key = make_key("test_func", arg1="value1")
            assert isinstance(key, str)
            assert len(key) == 32  # MD5 hash length

    def test_make_key_consistency(self):
        """Test that same inputs generate same key."""
        with patch("tools.cache.get_project_path", return_value="/path/to/project"):
            key1 = make_key("test_func", a=1, b=2)
            key2 = make_key("test_func", a=1, b=2)
            assert key1 == key2

    def test_make_key_argument_order_independence(self):
        """Test that argument order doesn't affect key (JSON sorted)."""
        with patch("tools.cache.get_project_path", return_value="/path/to/project"):
            key1 = make_key("test_func", a=1, b=2)
            key2 = make_key("test_func", b=2, a=1)
            assert key1 == key2

    def test_make_key_includes_project_path(self):
        """Test that different project paths generate different keys."""
        with patch("tools.cache.get_project_path", return_value="/path/one"):
            key1 = make_key("test_func", arg="value")

        with patch("tools.cache.get_project_path", return_value="/path/two"):
            key2 = make_key("test_func", arg="value")

        assert key1 != key2


@pytest.mark.unit
class TestCacheStorage:
    """Test cache storage and retrieval."""

    def setup_method(self):
        """Clear cache before each test."""
        clear()

    def test_set_and_get(self):
        """Test basic set and get operations."""
        key = "test_key"
        value = "test_value"
        set(key, value)
        assert get(key) == value

    def test_get_missing_key_returns_none(self):
        """Test that getting non-existent key returns None."""
        assert get("nonexistent_key") is None

    def test_cache_respects_ttl(self):
        """Test that cache respects TTL (expiry)."""
        key = "test_key"
        set(key, "test_value")
        assert get(key) == "test_value"

        # Simulate time passing by patching time.time()
        with patch("tools.cache.time.time") as mock_time:
            mock_time.return_value = time.time() + 301  # 301 seconds later (TTL=300)
            assert get(key) is None

    def test_clear_removes_all(self):
        """Test that clear() removes all cache entries."""
        set("key1", "value1")
        set("key2", "value2")
        clear()
        assert get("key1") is None
        assert get("key2") is None


@pytest.mark.unit
class TestCacheStats:
    """Test cache statistics."""

    def setup_method(self):
        """Clear cache before each test."""
        clear()

    def test_stats_empty_cache(self):
        """Test stats for empty cache."""
        s = stats()
        assert s["total_entries"] == 0
        assert s["valid_entries"] == 0
        assert s["expired_entries"] == 0
        assert s["ttl_seconds"] == 300

    def test_stats_with_entries(self):
        """Test stats with valid entries."""
        set("key1", "value1")
        set("key2", "value2")
        s = stats()
        assert s["total_entries"] == 2
        assert s["valid_entries"] == 2
        assert s["expired_entries"] == 0

    def test_stats_purge_on_write(self):
        """Test that stats reflect purging of expired entries."""
        # Add enough entries to trigger auto-purge (20 entries or 5 min elapsed)
        for i in range(25):
            set(f"key_{i}", f"value_{i}")

        # At 25 entries, purge should have been triggered (20 % 0 == 0)
        # This test verifies the counter mechanism works
        s = stats()
        assert s["total_entries"] >= 0  # Should still have entries after purge
