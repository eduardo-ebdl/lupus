# Lupus Test Suite

## Overview

Lupus uses **pytest** for unit testing. Tests are organized by category and focus on fast, isolated validation of core functionality without external dependencies (LLM, file I/O, network).

## Structure

```
tests/
├── __init__.py
├── README.md (this file)
├── conftest.py          # Shared fixtures and configuration
│
└── unit/                # Unit tests (fast, mocked)
    ├── __init__.py
    ├── test_cache.py              # Cache module tests (make_key, get, set, TTL)
    ├── test_config.py             # Configuration tests (MAX_CONTEXT_BYTES, make_agent)
    ├── test_project_discovery.py  # Project discovery (Python framework, data files)
    ├── test_retriever.py          # Retriever singleton and thread safety
    └── test_repository_explorer.py # Repository exploration (file tree, file types)
```

## Running Tests

### Run all tests
```bash
pytest tests/
```

### Run only unit tests
```bash
pytest tests/unit/ -m unit
```

### Run specific test file
```bash
pytest tests/unit/test_cache.py -v
```

### Run specific test class
```bash
pytest tests/unit/test_cache.py::TestCacheKeyGeneration -v
```

### Run specific test
```bash
pytest tests/unit/test_cache.py::TestCacheKeyGeneration::test_make_key_basic -v
```

### Run with coverage report
```bash
pytest tests/ --cov=. --cov-report=html
```

## Test Markers

Tests use pytest markers for organization:

```bash
# Run only unit tests
pytest -m unit

# Run only integration tests (if added later)
pytest -m integration
```

## Fixtures

Common fixtures are defined in `conftest.py`:

### `temp_project_dir`
Creates a temporary directory for testing. Automatically cleaned up.

```python
def test_something(temp_project_dir):
    # temp_project_dir is a string path to a temporary directory
    file_path = os.path.join(temp_project_dir, "test.txt")
```

### `mock_project_files`
Creates a mock project with realistic files (Python, dbt, data, docs). Inherits `temp_project_dir`.

```python
def test_discover(mock_project_files):
    # mock_project_files is a Path object with main.py, dbt_project.yml, data files, etc.
    assert (mock_project_files / "main.py").exists()
```

### `mock_ctx_manager`
Mock ProjectContextManager pointing to temp directory.

```python
def test_with_context(mock_ctx_manager):
    # mock_ctx_manager.path == temp directory path
    assert mock_ctx_manager.context.path is not None
```

### `mock_checkpointer`
Mock Checkpointer for testing (avoids SQLite I/O).

```python
def test_agent_with_mock_checkpointer(mock_checkpointer):
    agent = make_agent(checkpointer=mock_checkpointer)
    # No ~/.lupus filesystem pollution
```

### `isolate_config`
Patches environment variables safely for config testing.

```python
def test_custom_config(isolate_config):
    isolate_config.setenv("LUPUS_MAX_CONTEXT_BYTES", "20000")
    # Changes are isolated to this test
```

## Mocking Strategies

### Mock filesystem
```python
from pathlib import Path
import tempfile

def test_file_reading(mock_project_files):
    file_path = mock_project_files / "main.py"
    content = file_path.read_text()
    assert len(content) > 0
```

### Mock external services
```python
from unittest.mock import patch, MagicMock

def test_agent():
    with patch("config.ChatGoogleGenerativeAI") as mock_llm:
        mock_llm.return_value = MagicMock()
        # Code that uses ChatGoogleGenerativeAI won't make API calls
```

### Mock context manager
```python
def test_with_project_path():
    with patch("core.context_manager.get_project_path", return_value="/tmp/test"):
        # Functions using get_project_path will see /tmp/test
```

## What NOT to Test

- **Don't test LLM behavior** — mock `ChatGoogleGenerativeAI`, don't call it
- **Don't test real file I/O** — use `mock_project_files` fixture instead of creating files
- **Don't test network** — mock `clone_repository` and GitHub API calls
- **Don't test database** — use `mock_checkpointer` instead of SQLite

## Adding New Tests

### Step 1: File Structure

Test files mirror module structure:
- `tools/cache.py` → `tests/unit/test_cache.py`
- `rag/retriever.py` → `tests/unit/test_retriever.py`

### Step 2: Template Copy/Paste

```python
import pytest
from pathlib import Path
from tools.your_module import your_function

@pytest.mark.unit
class TestYourFunctionality:
    """Test suite for your_function"""
    
    def test_basic_case(self, mock_project_files):
        """Test basic behavior"""
        # Setup
        input_data = "test"
        
        # Execute
        result = your_function(input_data)
        
        # Assert
        assert result is not None
        assert isinstance(result, str)
    
    def test_edge_case(self):
        """Test edge case (empty, None, etc)"""
        result = your_function("")
        assert result == expected_output
    
    def test_error_handling(self):
        """Test error conditions"""
        with pytest.raises(ValueError):
            your_function(invalid_input)
```

### Step 3: Naming Conventions

| Item | Pattern | Example |
|------|---------|---------|
| Test file | `test_<module_name>.py` | `test_cache.py` |
| Test class | `Test<Feature>` | `TestCacheKeyGeneration` |
| Test method | `test_<scenario>` | `test_make_key_with_spaces` |
| Fixture | `<type>_<description>` | `mock_project_files`, `temp_dir` |

### Step 4: Example: Testing a New Tool

Se você adicionou uma ferramenta `analyze_code_quality`, aqui está o teste:

```python
# tests/unit/test_code_quality.py

import pytest
from tools.code_quality import analyze_code_quality

@pytest.mark.unit
class TestCodeQualityAnalyzer:
    """Tests for analyze_code_quality tool"""
    
    def test_analyze_python_file(self, mock_project_files):
        """Test basic code analysis"""
        file_path = mock_project_files / "main.py"
        
        result = analyze_code_quality(str(file_path))
        
        assert "complexity" in result
        assert "issues" in result
        assert len(result["issues"]) >= 0
    
    def test_analyze_nonexistent_file(self):
        """Test behavior with missing file"""
        with pytest.raises(FileNotFoundError):
            analyze_code_quality("/nonexistent/path.py")
    
    def test_analyze_supports_multiple_languages(self, mock_project_files):
        """Test multi-language support (Python, JS, SQL)"""
        # Python
        result_py = analyze_code_quality(str(mock_project_files / "main.py"))
        assert "python" in result_py.get("language", "").lower()
        
        # SQL
        result_sql = analyze_code_quality(str(mock_project_files / "query.sql"))
        assert "sql" in result_sql.get("language", "").lower()
```

**Rodando:**
```bash
pytest tests/unit/test_code_quality.py -v
```

### Step 5: Best Practices

1. **Use fixtures** — leverage `conftest.py` fixtures instead of writing setup code:
   ```python
   def test_something(mock_project_files):  # Injects fixture
       result = some_function(str(mock_project_files))
   ```

2. **Mark as unit** — all tests should have `@pytest.mark.unit`
   ```python
   @pytest.mark.unit
   class TestSomething:
       def test_case(self):
           pass
   ```

3. **Keep tests focused** — one assertion per test when possible:
   ```python
   def test_caching_stores_value(self):
       set("key", "value")
       assert get("key") == "value"

   def test_caching_respects_ttl(self):
       # TTL testing in separate test
   ```

4. **Use descriptive names** — test names should describe what they test:
   ```python
   def test_make_key_consistency(self):  # ✓ Good
   def test_key(self):                  # ✗ Too generic
   ```

## Continuous Integration

Currently, there is no GitHub Actions CI configured. To add:

1. Create `.github/workflows/tests.yml`
2. Configure to run `pytest tests/` on each PR
3. Require passing tests before merge

See MAINTENANCE.md for future CI setup tasks.

## Troubleshooting

### Fixture not found
```
fixture 'temp_project_dir' not found
```
→ Make sure `conftest.py` is in the test directory and pytest discovers it.

### Import errors
```
ModuleNotFoundError: No module named 'tools'
```
→ Make sure you run `pytest` from the project root: `pytest tests/`

### Mock not working
```
Expected mock to be called, but it wasn't
```
→ Check patch path: use `patch("module.ClassName")` not `patch("ClassName")`

---

**Last updated:** 2026-03-31
