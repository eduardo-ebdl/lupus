# Lupus Tools — Referência Completa

Documentação detalhada de todas as 17 ferramentas disponíveis no Lupus, agrupadas em 5 categorias.

---

## ⚡ Cheat Sheet — 17 Ferramentas

| # | Ferramenta | O que faz | Quando usar |
|---|-----------|----------|----------|
| **Discovery (5)** | | | |
| 1 | `discover_project` | Detecta stack tecnológico | Primeira pergunta sobre o projeto |
| 2 | `explore_repository` | Enumera estrutura de arquivos | Visão geral completa; entrada para `suggest_improvements` |
| 3 | `read_data_file` | Lê CSV, JSON, Parquet, Excel | Quando há dados locais no repositório |
| 4 | `clone_repository` | Clona repo GitHub | Trocar de repositório (mas veja `analyze_full_repository`) |
| 5 | `analyze_full_repository` | Clone + explore + read em 1x | ✅ Sempre que usuário enviar URL GitHub |
| **Domain (7)** | | | |
| 6 | `get_project_architecture` | Análise de camadas e arquitetura | "Qual a arquitetura?" |
| 7 | `analyze_dbt_model` | SQL, dependências, testes de 1 modelo | Detalhes de modelo dbt específico |
| 8 | `map_data_lineage` | Origem → transformações → destino | "Como dados fluem?" |
| 9 | `analyze_pipeline_config` | Jobs, schedule, orquestração | "Qual o schedule?" |
| 10 | `get_data_dictionary` | Schema, colunas, tipos, descrições | "Quais colunas existem?" |
| 11 | `map_code_dependencies` | Grafo de imports, módulos centrais | "Qual arquivo mais importado?" |
| 12 | `get_agent_tools_spec` | LLM config, tools, guardrails | Repositórios com AI agents |
| **Síntese (4)** | | | |
| 13 | `analyze_code` | Lê + explica arquivo específico | "Explique o arquivo X" |
| 14 | `generate_documentation` | Gera Markdown ou ABNT | Produzir documentação automática |
| 15 | `review_architecture` | Análise crítica de decisões | "Por que fizeram Y?" |
| 16 | `suggest_improvements` | Sugestões priorizadas | "Quais melhorias?" |
| **RAG (1)** | | | |
| 17 | `search_codebase` | Busca semântica no código | "Como é criado o campo X?" |

---

## Discovery Tools (5)

Ferramentas para exploração inicial e mapeamento do repositório.

### `discover_project`
**Propósito:** Detecta stack tecnológico, estrutura e frameworks presentes no repositório.

**Parâmetros:** Nenhum

**Retorna:** JSON com:
- `project_root`: Caminho raiz do repositório
- `technologies`: Dicionário com detecção de: dbt, Node.js, Python, Go, Java, Terraform, Docker, Kubernetes, Jupyter notebooks, Databricks
- `framework`: Framework principal detectado (se houver)
- `jupyter_notebooks`: Lista de notebooks encontrados

**Exemplo de uso:**
```
"Qual stack usa esse projeto?"
"Tem dbt?"
"Detecta Python ou Node?"
```

**⚠️ Armadilha comum:** Não detecta linguagens minoritárias (Scala, Rust, Kotlin). Use `explore_repository` para lista completa de tipos de arquivo.

### `explore_repository`
**Propósito:** Enumera estrutura de arquivos com análise de padrões.

**Parâmetros:**
- `max_depth` (int, padrão: 3): Profundidade máxima de recursão nos diretórios

**Retorna:** JSON com:
- `total_files`: Número total de arquivos
- `type_summary`: Contagem de arquivos por tipo (.sql, .py, .js, etc)
- `key_files`: Arquivos importantes detectados (README, config, manifests)
- `directories`: Estrutura de diretórios

**Exemplo de uso:**
```
"Mostre a estrutura do repositório"
"Quantos arquivos SQL tem?"
"Liste os diretórios principais"
```

### `clone_repository`
**Propósito:** Clona repositório GitHub público e configura o agente para analisá-lo.

**Parâmetros:**
- `url` (str): URL HTTPS ou SSH do GitHub (ex: `https://github.com/dbt-labs/jaffle_shop`)
- `branch` (str, opcional): Branch específico para clonar

**Retorna:** JSON com:
- `status`: "ok" se sucesso
- `repository`: Nome do repo
- `cloned_to`: Caminho local onde foi clonado
- `project_path_updated`: Confirmação de que PROJECT_PATH foi atualizado
- `discovery`: Resultado de detecção de stack automática

**Exemplo de uso:**
```
/repo https://github.com/dbt-labs/jaffle_shop
```

**Comportamento:**
- Clona com `--depth 1` (shallow clone, mais rápido)
- Repositórios anteriores são arquivados em `~/.lupus-repos/.archive/` com timestamp
- Mantém últimos 5 arquivos automaticamente
- Dispara hooks para invalidar RAG cache

**⚠️ Armadilha comum:** Use `analyze_full_repository` ao invés desta quando o usuário quer **análise completa**. `clone_repository` apenas clona; `analyze_full_repository` clona + explora + analisa em 1x.

### `analyze_full_repository`
**Propósito:** Pipeline integrado: clona + explora + lê arquivos + mapeia dependências em uma única chamada.

**Parâmetros:**
- `url` (str): URL do GitHub
- `branch` (str, opcional): Branch específico

**Retorna:** JSON consolidado com:
- Informações de clone
- Estrutura completa do repositório
- Conteúdo dos principais arquivos
- Resumo de dependências

**Quando usar:**
- ✅ Quando o usuário envia uma URL e quer análise completa imediatamente
- ✅ Melhor que chamar `clone_repository` + múltiplas outras ferramentas

**Exemplo de uso:**
```
"Analise https://github.com/user/repo"
```

**⚠️ Armadilha comum:** Essa ferramenta é pesada (leva 10-30s dependendo do tamanho do repo). Se o usuário só quer clonar rápido, use `clone_repository`.

### `read_data_file`
**Propósito:** Lê e analisa dados estruturados (CSV, JSON, Parquet, Excel).

**Parâmetros:**
- `file_path` (str): Caminho relativo do arquivo (ex: `data/sample.csv`)
- `max_rows` (int, padrão: 100): Máximo de linhas a retornar
- `column_filter` (str, opcional): Nomes de colunas a incluir (separados por vírgula)

**Retorna:** JSON com:
- `schema`: Nomes e tipos de colunas
- `preview`: Primeiras linhas dos dados
- `statistics`: Contagem, valores nulos, estatísticas descritivas

**Limitações:**
- Máximo 100 linhas por padrão (evita sobrecarga)
- Parquet: detecta schema automaticamente
- Excel: lê primeira sheet

**Exemplo de uso:**
```
"Leia o arquivo dados/vendas.csv"
"Qual é o schema do arquivo bruto.parquet?"
```

---

## Domain Analysis Tools (7)

Ferramentas especializadas para análise estruturada de componentes técnicos.

### `get_project_architecture`
**Propósito:** Analisa arquitetura do projeto identificando camadas (Medallion, modularização, fluxo de dados).

**Parâmetros:** Nenhum

**Retorna:** JSON com:
- `architecture_type`: Tipo detectado (Medallion, tradicional, etc)
- `layers`: Descrição de cada camada (Bronze, Silver, Gold) se aplicável
- `modules`: Módulos principais e suas responsabilidades
- `flow`: Fluxo de dados entre componentes

**Exemplo de uso:**
```
"Qual é a arquitetura do projeto?"
"Explique as camadas Bronze, Silver e Gold"
"Como a data flui entre módulos?"
```

### `analyze_dbt_model`
**Propósito:** Análise detalhada de um modelo dbt específico (SQL, testes, materialização, documentação).

**Parâmetros:**
- `model_name` (str): Nome do modelo (ex: `silver_srag_data`)
- `depth` (int, padrão: 2): Profundidade de dependências a incluir

**Retorna:** JSON com:
- `name`: Nome do modelo
- `path`: Caminho do arquivo
- `materialization`: Tipo (table, view, incremental, etc)
- `layer`: Camada (bronze, silver, gold)
- `sql_summary`: Resumo do SQL
- `dependencies`: Modelos que este depende
- `tests`: Testes associados
- `documentation`: Descrição do modelo

**Exemplo de uso:**
```
"Analise o modelo silver_srag_data"
"Qual o SQL do bronze_raw?"
```

### `map_data_lineage`
**Propósito:** Rastreamento completo de linhagem de dados (origem → transformações → destino final).

**Parâmetros:** Nenhum

**Retorna:** JSON com:
- `lineage_graph`: Grafo de dependências
- `sources`: Tabelas/datasets de origem
- `transformations`: Etapas de transformação
- `destinations`: Tabelas finais (Gold)
- `layer_summary`: Resumo por camada

**Exemplo de uso:**
```
"Como o obito_srag_flag é criado?"
"Qual a linhagem de dados até a tabela final?"
"Que transformações sofre os dados no Silver?"
```

### `analyze_pipeline_config`
**Propósito:** Análise de orquestração e configurações de pipeline (Databricks Asset Bundles, Airflow, etc).

**Parâmetros:** Nenhum

**Retorna:** JSON com:
- `orchestrator`: Tipo de orquestrador detectado
- `schedule`: Schedule/frequency das execuções
- `jobs`: Lista de jobs/tasks
- `dependencies`: Dependências entre jobs
- `deployment`: Config de deploy

**Exemplo de uso:**
```
"Qual o schedule do pipeline?"
"Como é feito o deploy?"
"Quantos jobs são executados?"
```

### `get_data_dictionary`
**Propósito:** Extração e documentação de schema (colunas, tipos, descrições por camada).

**Parâmetros:**
- `layer` (str, opcional): Filtrar por camada (bronze, silver, gold)

**Retorna:** JSON com:
- `tables`: Lista de tabelas por camada
- Cada tabela contém:
  - `columns`: Nomes e tipos de dados
  - `descriptions`: Descrições de colunas (se documentadas)
  - `row_count`: Estimativa de linhas
  - `materialization`: Tipo da tabela

**Exemplo de uso:**
```
"Quais colunas tem a Gold?"
"Qual o tipo do campo obito_flag?"
"Mostre o dicionário de dados"
```

### `map_code_dependencies`
**Propósito:** Análise de grafo de dependências entre arquivos de código (imports Python, requires JS, imports Go).

**Parâmetros:** Nenhum

**Retorna:** JSON com:
- `dependency_graph`: Grafo completo
- `central_modules`: Arquivos mais importados (high coupling)
- `leaf_modules`: Arquivos que não importam outros
- `external_deps`: Bibliotecas externas usadas
- `languages`: Linguagens detectadas

**Exemplo de uso:**
```
"Qual arquivo é mais importado?"
"Quais são as dependências externas?"
"Há ciclos de dependência?"
```

### `get_agent_tools_spec`
**Propósito:** Especificação de agentes IA presentes (tools, guardrails, integrações, prompts).

**Parâmetros:** Nenhum

**Retorna:** JSON com:
- `agents`: Lista de agentes detectados
- Para cada agente:
  - `tools`: Tools disponíveis
  - `guardrails`: Restrições e validações
  - `llm_config`: Configuração do LLM
  - `integrations`: APIs/sistemas integrados

**Exemplo de uso:**
```
"Qual ferramenta o agent usa?"
"Quais guardrails estão implementados?"
```

---

## Synthesis Sub-Agents (4)

Ferramentas que sintetizam análises através de invocação interna do LLM.

### `analyze_code`
**Propósito:** Lê um arquivo específico do repositório e responde perguntas sobre seu conteúdo.

**Parâmetros:**
- `file_path` (str): Caminho relativo do arquivo (ex: `models/silver/sql/arquivo.sql`)
- `question` (str): Pergunta específica sobre o arquivo

**Validações:**
- `file_path`: máximo 200 caracteres
- `question`: máximo 500 caracteres
- Segurança: rejeita path traversal (ex: `../../etc/passwd`)

**Retorna:** Análise textual do Gemini sobre o código

**Exemplo de uso:**
```
"Leia models/silver.sql e explique como funciona"
"No arquivo config.yaml, qual o intervalo de atualização?"
```

### `generate_documentation`
**Propósito:** Gera documentação técnica em Markdown ou YAML a partir do repositório.

**Parâmetros:**
- `topic` (str): Tópico (ex: `README completo`, `arquitetura`, `pipeline de dados`)
- `output_filename` (str, opcional): Nome do arquivo (ex: `doc.md`, `report.yml`)
  - Extensões válidas: `.md`, `.yml`, `.yaml`, `.txt`
- `style` (str, padrão: `tecnico`):
  - `tecnico`: Markdown técnico conciso para README/docs
  - `abnt`: Documento acadêmico formal ABNT em YAML (8-10 páginas)

**Validações:**
- `topic`: máximo 200 caracteres
- `output_filename`: máximo 100 caracteres
- `style`: apenas "tecnico" ou "abnt"

**Comportamento:**
- Salva automaticamente em `generated_docs/` e no repositório analisado
- Se `output_filename` vazio, gera nome a partir do tópico

**Exemplo de uso:**
```
"Gere documentação da arquitetura em Markdown"
"Crie um relatório ABNT sobre o pipeline de dados"
```

### `review_architecture`
**Propósito:** Análise crítica profunda de decisões de design e padrões arquiteturais.

**Parâmetros:**
- `question` (str): Pergunta sobre arquitetura (ex: `por que o bronze é ephemeral?`)

**Validações:**
- `question`: máximo 500 caracteres

**Comportamento:**
- Reúne contexto de múltiplas ferramentas (discovery, lineage, dbt, pipeline, agent spec)
- Aplica raciocínio crítico com base em evidências do projeto
- Avalia trade-offs e alternativas

**Exemplo de uso:**
```
"Por que o bronze é ephemeral?"
"Quais os trade-offs do liquid clustering?"
"Como você avalia essa decisão arquitetural?"
```

### `suggest_improvements`
**Propósito:** Análise crítica do repositório com sugestões priorizadas de melhoria.

**Parâmetros:**
- `focus` (str, opcional): Área específica (ex: `arquitetura`, `testes`, `segurança`, `performance`)

**Validações:**
- `focus`: máximo 100 caracteres

**Retorna:** Sugestões organizadas por categoria:
- Cada sugestão contém:
  - Problema/oportunidade identificado
  - Por que importa (impacto real)
  - Como implementar (ação concreta)
  - Prioridade (Alta/Média/Baixa)

**Exemplo de uso:**
```
"Sugira melhorias no projeto"
"Foco em segurança: o que pode melhorar?"
"Recomendações para performance?"
```

---

## Search Tool (1)

### `search_codebase`
**Propósito:** Busca híbrida no código-fonte usando múltiplas estratégias em pipeline.

**Parâmetros:**
- `query` (str): Termo de busca ou pergunta (ex: `como normalizar datas?`)
- `k` (int, padrão: 5): Número de resultados a retornar
- `layer` (str, opcional): Filtrar por camada (bronze, silver, gold)

**Pipeline de busca:**
1. **FAISS Semântico** (bi-encoder): Busca vetorial por similaridade semântica
2. **BM25 Keyword**: Correspondência exata de termos
3. **Reciprocal Rank Fusion (RRF)**: Fusão de rankings sem calibração manual
4. **CrossEncoder Reranking**: Reranking preciso em ~15 top chunks

**Retorna:** Lista de resultados com:
- `content`: Trecho do código/documentação
- `file_path`: Caminho do arquivo
- `layer`: Camada (se aplicável)
- `chunk_type`: Tipo (python_function, sql_model, markdown_section, etc)
- `score`: Score de relevância (0-1)

**Validação:**
- Primeiro acesso baixa modelos de embedding (380MB, ~1 min)
- Requer índice RAG sincronizado (avisa se desatualizado)

**Exemplo de uso:**
```
"Como a idade é normalizada?"
"Onde é criado o obito_flag?"
"Qual função trata dados nulos?"
```

**⚠️ Armadilha comum:** Se o índice está desatualizado (você clonou novo repo), a busca retorna resultados do repo antigo. Execute `python scripts/build_rag_index.py` para reindexar.

---

## Dicas de Uso

### Combinando Tools

Muitos casos de uso combinam várias ferramentas automaticamente. Aqui estão padrões práticos:

#### Exemplo 1: Análise de novo repositório
```
Pergunta: "Analisa https://github.com/dbt-labs/jaffle_shop"

Ferramentas chamadas:
1. analyze_full_repository(url) — clona + explora + lê arquivos
2. Com resultado, agent chama get_project_architecture automaticamente
3. Retorna: stack, arquitetura, principais módulos

Resultado final: Análise completa em 1 pergunta
```

#### Exemplo 2: Entender fluxo de dados
```
Pergunta: "Como os dados fluem do Bronze ao Gold?"

Ferramentas chamadas:
1. discover_project — confirma que é projeto dbt
2. map_data_lineage — obtém grafo completo
3. analyze_dbt_model (para 2-3 modelos-chave) — SQL e transformações
4. get_data_dictionary (layer=gold) — schema final

Resultado: Fluxo visual com exemplos de SQL
```

#### Exemplo 3: Sugestões contextualizadas
```
Pergunta: "Quais melhorias você sugere?"

Ferramentas chamadas:
1. discover_project — detecta stack e padrões
2. explore_repository — estrutura completa
3. map_code_dependencies — acoplamento, entry points
4. suggest_improvements (focus=None) — análise com tudo isso

Resultado: Sugestões priorizadas por categoria (arquitetura, testes, segurança, performance)
```

#### Exemplo 4: Buscar implementação específica
```
Pergunta: "Onde é criado o campo idade_normalizada?"

Ferramentas chamadas:
1. search_codebase(query="idade_normalizada") — busca híbrida
2. Se encontrar, retorna arquivo + trecho de código
3. Se precisar mais detalhe, analyze_code(arquivo) — explicação completa

Resultado: Implementação encontrada + explicação
```

### Ordem recomendada para novo repositório
1. `discover_project` — entender stack
2. `explore_repository` — ver estrutura
3. `get_project_architecture` — entender design
4. `map_data_lineage` ou `analyze_pipeline_config` — fluxo de dados
5. Perguntas específicas com `analyze_code` ou `search_codebase`

### Limites e Performance
- **Repository size**: Análises suportam repos de até ~50MB
- **File reading**: Máximo 1500 caracteres por arquivo (evita streaming infinito)
- **Search results**: Máximo 5 resultados por padrão (evita sobrecarga)
- **Timeout**: Agente tem limite de 3 minutos por resposta

---

## Resolução de Problemas

### "Tool returned error"
- Verifique se o caminho/nome do arquivo está correto
- Use caminhos relativos (ex: `models/silver/arquivo.sql`, não caminho absoluto)
- Se for data file, confirme que é CSV/JSON/Parquet/Excel válido

### "Índice RAG desatualizado"
- Rode: `python scripts/build_rag_index.py`
- Aguarde (primeira vez leva ~1-2 min)

### "HuggingFace model download trava"
- Defina: `export HF_HUB_DOWNLOAD_TIMEOUT=600`
- Aguarde até 5 minutos (primeiro download é grande)

