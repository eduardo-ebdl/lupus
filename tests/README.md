# Suite de Testes do Lupus

## Visão Geral

Lupus usa **pytest** para testes unitários. Os testes são organizados por categoria e focam em validação rápida e isolada da funcionalidade central sem dependências externas (LLM, I/O, rede).

## Estrutura

```
tests/
├── __init__.py
├── README.md (este arquivo)
├── conftest.py          # Fixtures compartilhadas e configuração
│
└── unit/                # Testes unitários (rápidos, com mock)
    ├── __init__.py
    ├── test_cache.py              # Testes do cache (make_key, get, set, TTL)
    ├── test_config.py             # Testes de configuração (MAX_CONTEXT_BYTES, make_agent)
    ├── test_project_discovery.py  # Discovery de projeto (frameworks, arquivos de dados)
    ├── test_retriever.py          # Singleton retriever e thread safety
    └── test_repository_explorer.py # Exploração de repositório (árvore, tipos)
```

## Executando Testes

### Executar todos os testes
```bash
pytest tests/
```

### Executar apenas testes unitários
```bash
pytest tests/unit/ -m unit
```

### Executar arquivo específico
```bash
pytest tests/unit/test_cache.py -v
```

### Executar classe de teste específica
```bash
pytest tests/unit/test_cache.py::TestCacheKeyGeneration -v
```

### Executar teste específico
```bash
pytest tests/unit/test_cache.py::TestCacheKeyGeneration::test_make_key_basic -v
```

### Executar com relatório de cobertura
```bash
pytest tests/ --cov=. --cov-report=html
```

## Marcadores de Teste

Os testes usam marcadores pytest para organização:

```bash
# Executar apenas testes unitários
pytest -m unit

# Executar apenas testes de integração (se adicionados depois)
pytest -m integration
```

## Fixtures

Fixtures comuns estão definidas em `conftest.py`:

### `temp_project_dir`
Cria um diretório temporário para testes. Limpado automaticamente.

```python
def test_something(temp_project_dir):
    # temp_project_dir é um caminho string para diretório temporário
    file_path = os.path.join(temp_project_dir, "test.txt")
```

### `mock_project_files`
Cria um projeto mock com arquivos realistas (Python, dbt, dados, docs). Herda `temp_project_dir`.

```python
def test_discover(mock_project_files):
    # mock_project_files é um objeto Path com main.py, dbt_project.yml, etc.
    assert (mock_project_files / "main.py").exists()
```

### `mock_ctx_manager`
Mock ProjectContextManager apontando para diretório temporário.

```python
def test_with_context(mock_ctx_manager):
    # mock_ctx_manager.path == caminho do diretório temporário
    assert mock_ctx_manager.context.path is not None
```

### `mock_checkpointer`
Mock Checkpointer para testes (evita I/O do SQLite).

```python
def test_agent_with_mock_checkpointer(mock_checkpointer):
    agent = make_agent(checkpointer=mock_checkpointer)
    # Sem poluição do filesystem ~/.lupus
```

### `isolate_config`
Faz patch de variáveis de ambiente com segurança para testes de config.

```python
def test_custom_config(isolate_config):
    isolate_config.setenv("LUPUS_MAX_CONTEXT_BYTES", "20000")
    # Mudanças são isoladas para este teste
```

## Estratégias de Mock

### Mock de filesystem
```python
from pathlib import Path
import tempfile

def test_file_reading(mock_project_files):
    file_path = mock_project_files / "main.py"
    content = file_path.read_text()
    assert len(content) > 0
```

### Mock de serviços externos
```python
from unittest.mock import patch, MagicMock

def test_agent():
    with patch("config.ChatGoogleGenerativeAI") as mock_llm:
        mock_llm.return_value = MagicMock()
        # Código usando ChatGoogleGenerativeAI não faz chamadas de API
```

### Mock de gerenciador de contexto
```python
def test_with_project_path():
    with patch("core.context_manager.get_project_path", return_value="/tmp/test"):
        # Funções usando get_project_path verão /tmp/test
```

## O que NÃO testar

- **Não teste comportamento de LLM** — faça mock de `ChatGoogleGenerativeAI`, não chame
- **Não teste I/O real** — use fixture `mock_project_files` ao invés de criar arquivos
- **Não teste rede** — faça mock de `clone_repository` e chamadas de GitHub API
- **Não teste banco de dados** — use `mock_checkpointer` ao invés de SQLite

## Adicionando Novos Testes

### Passo 1: Estrutura de Arquivo

Arquivos de teste espelham a estrutura de módulos:
- `tools/cache.py` → `tests/unit/test_cache.py`
- `rag/retriever.py` → `tests/unit/test_retriever.py`

### Passo 2: Template Copy/Paste

```python
import pytest
from pathlib import Path
from tools.seu_modulo import sua_funcao

@pytest.mark.unit
class TestSuaFuncionalidade:
    """Suite de testes para sua_funcao"""
    
    def test_caso_basico(self, mock_project_files):
        """Teste comportamento básico"""
        # Setup
        dados_entrada = "teste"
        
        # Executa
        resultado = sua_funcao(dados_entrada)
        
        # Assertiva
        assert resultado is not None
        assert isinstance(resultado, str)
    
    def test_caso_extremo(self):
        """Teste caso extremo (vazio, None, etc)"""
        resultado = sua_funcao("")
        assert resultado == saida_esperada
    
    def test_tratamento_erro(self):
        """Teste condições de erro"""
        with pytest.raises(ValueError):
            sua_funcao(entrada_invalida)
```

### Passo 3: Convenções de Nomenclatura

| Item | Padrão | Exemplo |
|------|--------|---------|
| Arquivo de teste | `test_<nome_modulo>.py` | `test_cache.py` |
| Classe de teste | `Test<Funcionalidade>` | `TestCacheKeyGeneration` |
| Método de teste | `test_<cenario>` | `test_make_key_with_spaces` |
| Fixture | `<tipo>_<descricao>` | `mock_project_files`, `temp_dir` |

### Passo 4: Exemplo: Testando Uma Ferramenta Nova

Se você adicionou uma ferramenta `analyze_code_quality`, aqui está o teste:

```python
# tests/unit/test_code_quality.py

import pytest
from tools.code_quality import analyze_code_quality

@pytest.mark.unit
class TestCodeQualityAnalyzer:
    """Testes para ferramenta analyze_code_quality"""
    
    def test_analyze_python_file(self, mock_project_files):
        """Teste análise básica de código"""
        file_path = mock_project_files / "main.py"
        
        result = analyze_code_quality(str(file_path))
        
        assert "complexity" in result
        assert "issues" in result
        assert len(result["issues"]) >= 0
    
    def test_analyze_nonexistent_file(self):
        """Teste comportamento com arquivo faltando"""
        with pytest.raises(FileNotFoundError):
            analyze_code_quality("/nonexistent/path.py")
    
    def test_analyze_supports_multiple_languages(self, mock_project_files):
        """Teste suporte a múltiplas linguagens (Python, JS, SQL)"""
        # Python
        result_py = analyze_code_quality(str(mock_project_files / "main.py"))
        assert "python" in result_py.get("language", "").lower()
        
        # SQL
        result_sql = analyze_code_quality(str(mock_project_files / "query.sql"))
        assert "sql" in result_sql.get("language", "").lower()
```

**Executando:**
```bash
pytest tests/unit/test_code_quality.py -v
```

### Passo 5: Boas Práticas

1. **Use fixtures** — aproveite fixtures de `conftest.py` ao invés de escrever código de setup:
   ```python
   def test_something(mock_project_files):  # Injeta fixture
       result = some_function(str(mock_project_files))
   ```

2. **Marque como unit** — todos os testes devem ter `@pytest.mark.unit`
   ```python
   @pytest.mark.unit
   class TestAlgo:
       def test_case(self):
           pass
   ```

3. **Mantenha testes focados** — uma assertiva por teste quando possível:
   ```python
   def test_caching_stores_value(self):
       set("key", "value")
       assert get("key") == "value"

   def test_caching_respects_ttl(self):
       # Teste de TTL em teste separado
   ```

4. **Use nomes descritivos** — nomes de teste devem descrever o que testam:
   ```python
   def test_make_key_consistency(self):  # ✓ Bom
   def test_key(self):                  # ✗ Muito genérico
   ```

## Integração Contínua

Atualmente não há GitHub Actions CI configurada. Para adicionar:

1. Crie `.github/workflows/tests.yml`
2. Configure para rodar `pytest tests/` em cada PR
3. Exija testes passando antes de merge

## Resolução de Problemas

### Fixture não encontrada
```
fixture 'temp_project_dir' not found
```
→ Certifique-se que `conftest.py` está no diretório de testes e pytest a descobre.

### Erros de import
```
ModuleNotFoundError: No module named 'tools'
```
→ Certifique-se que você roda `pytest` da raiz do projeto: `pytest tests/`

### Mock não funciona
```
Expected mock to be called, but it wasn't
```
→ Verifique caminho do patch: use `patch("module.ClassName")` não `patch("ClassName")`
