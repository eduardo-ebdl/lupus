# Lupus — AI Code Intelligence Agent

**Projeto pessoal de estudos** em AI Engineering. Lupus é um agente conversacional para análise de repositórios — experimenta integração de LangGraph, ferramentas especializadas, busca semântica local e avaliação com LLM como juiz. 

O agente consulta os arquivos reais do projeto através de 17 ferramentas. Todas as respostas são fundamentadas no código-fonte analisado, sem extrapolações baseadas em conhecimento geral.

---

## ⚡ Quick Start

```bash
# Setup (2 min)
git clone https://github.com/seu-usuario/lupus.git && cd lupus
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# Configure GOOGLE_API_KEY em https://aistudio.google.com/app/apikey

# Rodar (primeira vez: ~2 min para build do índice RAG)
python scripts/build_rag_index.py
python main.py
```

Teste com: `"Qual a arquitetura do projeto?"` ou `"Analisa https://github.com/dbt-labs/jaffle_shop"`

---

## 📖 Índice

- [Capacidades](#capacidades) — 17 ferramentas para análise de repositórios
- [Arquitetura](#arquitetura) — Como funciona internamente
- [Stack Tecnológico](#stack-tecnológico) — Ferramentas e bibliotecas
- [Configuração](#configuração) — Setup, dependências e variáveis de ambiente
- [Configuração de Repositório](#configuração-de-repositório) — Como especificar qual repo analisar
- [Avaliação](#avaliação) — Métricas e dataset de teste
- [LupusAPI](#lupusapi--camada-http) — REST API com FastAPI
- [Troubleshooting](#troubleshooting) — Problemas comuns e soluções
- [Blocos de Desenvolvimento](#blocos-de-desenvolvimento) — Histórico de implementação
- [Learn More](#learn-more) — Outros documentos

---

## Capacidades

O agente fornece análise técnica de repositórios através de 17 ferramentas organizadas em 4 categorias:

### Ferramentas de Discovery (5)

Mapeamento automático e exploração inicial do repositório:
- `discover_project`: detecção de stack tecnológico (dbt, Node.js, Go, Java, Terraform, Kubernetes, Docker, Jupyter notebooks)
- `explore_repository`: enumeração de estrutura de arquivos com análise de padrões de segurança
- `read_data_file`: análise de dados estruturados (CSV, JSON, Parquet, Excel)
- `clone_repository`: clonagem de repositórios GitHub públicos com atualização automática do contexto
- `analyze_full_repository`: pipeline integrado de clonagem, exploração e análise

### Ferramentas de Análise de Domínio (7)

Análise estruturada de componentes específicos através da leitura de arquivos reais:
- `get_project_architecture`: análise de arquitetura (Medallion Architecture, modularização, fluxo de dados)
- `analyze_dbt_model`: análise de modelos dbt (camadas Bronze/Silver/Gold, transformações SQL, testes)
- `map_data_lineage`: rastreamento de linhagem de dados (origem até camadas finais)
- `analyze_pipeline_config`: análise de pipelines (DABs, schedule, deploy, orquestração)
- `get_data_dictionary`: extração de schema (colunas, tipos de dados, descrições por camada)
- `map_code_dependencies`: análise de grafo de dependências (imports Python/JS/TS/Go, bibliotecas externas)
- `get_agent_tools_spec`: especificação de agentes (tools, guardrails, integrações)

### Sub-agentes para Síntese (4)

Análise de nível superior através de invocação interna do LLM:
- `analyze_code`: leitura e explicação de arquivo específico
- `generate_documentation`: geração de documentação em formato Markdown
- `review_architecture`: análise crítica de decisões arquiteturais
- `suggest_improvements`: recomendações baseadas em análise do repositório

### Busca Semântica (1)

- `search_codebase`: busca híbrida no código-fonte (FAISS para busca vetorial + BM25 para busca por palavra-chave + RRF para fusão de rankings + CrossEncoder para reranking)

## Geração de Documentação

A ferramenta `generate_documentation` produz documentação em formato Markdown a partir da análise do repositório. Exemplos de uso:

```
"Gera documentação completa da arquitetura"
"Cria diagrama em Markdown da linhagem de dados"
"Documenta as transformações principais do dbt"
```

A documentação gerada é salva automaticamente no diretório do projeto analisado.

---

## Arquitetura

### Fluxo de uma pergunta

```mermaid
flowchart TD
    User(["👤 Usuário"])
    
    User -->|pergunta| CLI["💻 CLI<br/>(main.py)"]
    
    CLI -->|invoca| Agent["🤖 Agent<br/>(LangGraph)"]
    
    Agent -->|carrega| Skill["📋 SKILL.md<br/>(persona)"]
    
    Agent -->|decisão| Decision{"Qual<br/>ferramenta?"}
    
    Decision -->|discovery| T1["🔍 discover_project<br/>explore_repository"]
    Decision -->|domínio| T2["📊 analyze_dbt_model<br/>map_data_lineage"]
    Decision -->|síntese| T3["✍️ generate_documentation<br/>review_architecture"]
    Decision -->|busca| T4["🔎 search_codebase<br/>(RAG)"]
    
    T1 --> Tools["⚙️ 17 Tools<br/>leem repositório"]
    T2 --> Tools
    T3 --> Tools
    T4 --> Tools
    
    Tools -->|resultado| LLM["⚡ Gemini<br/>2.5 Flash"]
    
    LLM -->|síntese| Response["📝 Resposta<br/>(no código)"]
    
    Response -->|output| User
    
    style User fill:#c7d2fe,stroke:#818cf8,stroke-width:2px,color:#333
    style CLI fill:#ddd6fe,stroke:#a78bfa,stroke-width:2px,color:#333
    style Agent fill:#fce7f3,stroke:#fbcfe8,stroke-width:2px,color:#333
    style Skill fill:#fef3c7,stroke:#fde68a,stroke-width:2px,color:#333
    style Decision fill:#d1fae5,stroke:#a7f3d0,stroke-width:2px,color:#333
    style T1 fill:#cffafe,stroke:#a5f3fc,stroke-width:1.5px,color:#333
    style T2 fill:#cffafe,stroke:#a5f3fc,stroke-width:1.5px,color:#333
    style T3 fill:#cffafe,stroke:#a5f3fc,stroke-width:1.5px,color:#333
    style T4 fill:#cffafe,stroke:#a5f3fc,stroke-width:1.5px,color:#333
    style Tools fill:#ddd6fe,stroke:#a78bfa,stroke-width:2px,color:#333
    style LLM fill:#fef3c7,stroke:#fde68a,stroke-width:2px,color:#333
    style Response fill:#c7d2fe,stroke:#818cf8,stroke-width:2px,color:#333
```

---

### Pipeline RAG — como `search_codebase` funciona internamente

```mermaid
flowchart LR
    subgraph Build["⚙️ BUILD-TIME"]
        Repo["📁 Repositório<br/>(.sql, .yml, .ipynb, .md)"]
        Chunk["🔪 Chunking<br/>(1 arquivo/chunk ou<br/>1 célula/seção)"]
        Embed["📊 Embeddings<br/>(all-MiniLM-L6-v2<br/>384 dims, local)"]
        Index["🗂️ Build FAISS Index<br/>(IndexFlatIP,<br/>cosine similarity)"]
        
        Repo --> Chunk --> Embed --> Index
    end
    
    Build -->|salva| Store["💾 rag/index/<br/>(gitignored)<br/>lupus.index<br/>+ metadata.json"]
    
    subgraph Query["🔍 QUERY-TIME"]
        Input["❓ User Query<br/>(ex: 'como<br/>obito_flag<br/>é criada?')"]
        
        Semantic["Semantic Search<br/>(FAISS)"]
        Keyword["Keyword Search<br/>(BM25)"]
        Fusion["Rank Fusion<br/>(RRF)"]
        Rerank["Rerank Preciso<br/>(CrossEncoder)"]
        Result["Top-5 Chunks<br/>com source"]
        
        Input --> Semantic
        Input --> Keyword
        Semantic --> Fusion
        Keyword --> Fusion
        Fusion --> Rerank --> Result
    end
    
    Store -->|carrega| Query
    Result -->|passa pro| LLM["⚡ Gemini<br/>(sintetiza<br/>resposta)"]
    
    style Build fill:#d1fae5,stroke:#a7f3d0,stroke-width:2px,color:#333
    style Repo fill:#cffafe,stroke:#a5f3fc,stroke-width:1.5px,color:#333
    style Chunk fill:#cffafe,stroke:#a5f3fc,stroke-width:1.5px,color:#333
    style Embed fill:#cffafe,stroke:#a5f3fc,stroke-width:1.5px,color:#333
    style Index fill:#cffafe,stroke:#a5f3fc,stroke-width:1.5px,color:#333
    style Store fill:#ddd6fe,stroke:#a78bfa,stroke-width:2px,color:#333
    style Query fill:#d1fae5,stroke:#a7f3d0,stroke-width:2px,color:#333
    style Input fill:#cffafe,stroke:#a5f3fc,stroke-width:1.5px,color:#333
    style Semantic fill:#fef3c7,stroke:#fde68a,stroke-width:1.5px,color:#333
    style Keyword fill:#fef3c7,stroke:#fde68a,stroke-width:1.5px,color:#333
    style Fusion fill:#fce7f3,stroke:#fbcfe8,stroke-width:1.5px,color:#333
    style Rerank fill:#fce7f3,stroke:#fbcfe8,stroke-width:1.5px,color:#333
    style Result fill:#c7d2fe,stroke:#818cf8,stroke-width:1.5px,color:#333
    style LLM fill:#fef3c7,stroke:#fde68a,stroke-width:2px,color:#333
```

---

### Quando o agente escolhe cada tool

| Pergunta do usuário | Tool acionada |
|---|---|
| "Quais tecnologias esse projeto usa?" | `discover_project` |
| "Me mostra a estrutura de arquivos do projeto" | `explore_repository` |
| "Tem algum CSV aqui? Me mostra as colunas" | `read_data_file` |
| "Analisa o repositório github.com/dbt-labs/jaffle_shop" | `analyze_full_repository` |
| "Qual a arquitetura do projeto?" | `get_project_architecture` |
| "O que faz este modelo SQL?" | `analyze_dbt_model` |
| "Como os dados fluem entre as camadas?" | `map_data_lineage` |
| "Qual o schedule do pipeline?" | `analyze_pipeline_config` |
| "Quais colunas estão disponíveis?" | `get_data_dictionary` |
| "Como o projeto usa o LLM?" | `get_agent_tools_spec` |
| "Quais módulos esse projeto importa mais?" | `map_code_dependencies` |
| "Leia o arquivo X para mim" | `analyze_code` |
| "Gere documentação da arquitetura" | `generate_documentation` |
| "Por que essa decisão arquitetural foi tomada?" | `review_architecture` |
| "Quais melhorias você sugere pro projeto?" | `suggest_improvements` |
| "Como campos derivados são criados no SQL?" | `search_codebase` |

## Stack Tecnológico

| Componente | Tecnologia | Justificativa |
|-----------|-----------|-----------|
| Framework de Agentes | DeepAgents (LangChain + LangGraph) | Memória de conversa com estado e middleware plugável |
| LLM | Flexível (Gemini, Claude, OpenAI) | Configurável via `LLM_PROVIDER` — padrão: Gemini 2.5 Flash |
| Busca Semântica | FAISS (local) + BM25 + RRF + CrossEncoder | Pipeline híbrido, sem API externa, dados locais |
| Framework CLI | Rich | Formatação estruturada de output (markdown, painéis, indicadores) |
| Sistema de Persona | SKILL.md + SkillsMiddleware | Instruções contextualizadas, comportamento consistente |
| Persistência de Conversas | SQLite | Memória multi-turn com suporte a checkpoint |
| Observabilidade | LangSmith (opcional) | Rastreamento automático, logging de invocação |
| Embeddings | sentence-transformers / HuggingFace | all-MiniLM-L6-v2, 384 dims, local (sem APIs externas) |

### Decisões de Design

- **Busca semântica local**: FAISS opera offline sem APIs externas. Dados sensíveis do repositório não saem da máquina do usuário.
- **Contexto em tempo real**: As ferramentas consultam arquivos reais do projeto; sem dependência de datas de treinamento.
- **Arquitetura modular**: Cada ferramenta é independentemente implantável e testável.
- **Auto-documentação**: O agente gera documentação descrevendo o repositório analisado.

### ⚠️ Dependência Alpha: DeepAgents 0.5.0a2

O Lupus usa **DeepAgents 0.5.0a2** — versão alpha que ainda pode sofrer mudanças. Esta é uma dependência necessária, mas você deve estar ciente dos potenciais problemas:

**Sintomas conhecidos:**
- Streaming pode ter timeout em contextos grandes (> 20KB)
- Requisições simultâneas podem causar race conditions em raros casos
- Mudanças de API entre versões alpha sem aviso prévio

**Como verificar se é um problema do DeepAgents:**
1. A resposta começa bem mas depois trava ou timeout?
2. Você consegue fazer a mesma pergunta com um arquivo menor e funciona?
3. Veja o troubleshooting em [MAINTENANCE.md](MAINTENANCE.md#troubleshooting-de-desenvolvimento)

**Plano de upgrade:**
- Quando DeepAgents 0.5.0 (versão final) for lançado, executaremos: `pip install deepagents==0.5.0 && pip freeze > requirements.lock`
- Você será notificado via issue/release do Lupus

---

## Estrutura do Projeto

```
lupus/
├── Pontos de Entrada
│   ├── main.py                    # Interface CLI
│   ├── config.py                  # Configuração central (LLM, ferramentas, middleware)
│   └── .env.example               # Template de variáveis de ambiente
│
├── Agente Principal
│   ├── core/
│   │   ├── context_manager.py     # Gerenciamento de estado e hooks de contexto
│   │   └── repo_context.py        # Metadados de repositório (caminho, cache, RAG sync)
│   └── skills/lupus/SKILL.md      # Definição de persona e restrições de comportamento
│
├── Ferramentas (17 total)
│   ├── tools/__init__.py          # Registro e exportação de ferramentas
│   │
│   ├── Ferramentas de Discovery (5)
│   │   ├── project_discovery.py   # Detecção de stack
│   │   ├── repository_explorer.py # Enumeração de estrutura de arquivos
│   │   ├── data_file_reader.py    # Análise de dados estruturados
│   │   ├── github_integration.py  # Clonagem de repositórios
│   │   └── full_analysis.py       # Pipeline de discovery combinado
│   │
│   ├── Ferramentas de Domínio (7)
│   │   ├── architecture.py        # Análise de arquitetura
│   │   ├── dbt_analyzer.py        # Análise de modelos dbt
│   │   ├── lineage.py             # Rastreamento de linhagem de dados
│   │   ├── pipeline_analyzer.py   # Análise de configuração de pipelines
│   │   ├── data_dictionary.py     # Extração de schema
│   │   ├── code_dependencies.py   # Análise de grafo de dependências
│   │   └── agent_analyzer.py      # Especificação de agentes
│   │
│   ├── Sub-agentes (4)
│   │   └── subagents.py           # analyze_code, generate_documentation, review, suggest
│   │
│   ├── Ferramentas RAG (1)
│   │   └── rag_search.py          # Busca semântica
│   │
│   └── Utilitários
│       ├── cache.py               # Cache com TTL
│       └── path_helpers.py        # Utilitários de resolução de caminho
│
├── Módulo RAG
│   ├── rag/
│   │   ├── indexer.py             # Chunking semântico + builder de índice FAISS
│   │   ├── retriever.py           # Busca híbrida + reranking com CrossEncoder
│   │   └── index/                 # Índices gerados (gitignored)
│
├── Testes e Avaliação
│   ├── tests/                     # Testes de integração
│   ├── evaluation/
│   │   ├── dataset.json           # Dataset de teste (25 perguntas)
│   │   └── run_evaluation.py      # Harness de avaliação com LLM como juiz
│   └── scripts/
│       ├── build_rag_index.py     # Builder de índice RAG
│       └── generate_docs.py       # Gerador de documentação
│
├── Documentação
│   ├── README.md
│   └── AGENTS.md                  # Contexto e diretrizes do agente
```

### Fluxo de Dados

```
Query de Entrada (main.py)
         ↓
    config.make_agent() → Executor LangGraph
         ↓
    Stack de Middleware (Skills, Memory, Filesystem)
         ↓
    Gemini 2.5 Flash (raciocínio + seleção de ferramentas)
         ↓
    Invocação de Ferramentas (discovery, domínio, RAG, sub-agentes)
         ↓
    I/O de Arquivo + Busca Semântica (pipeline RAG)
         ↓
    Síntese de Resposta do LLM
         ↓
    Formatação de Output via Rich CLI
         ↓
    Output do Usuário
```

## Configuração

### Setup Detalhado

```bash
# 1. Clonar repositório
git clone https://github.com/seu-usuario/lupus.git
cd lupus

# 2. Criar ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/macOS
# ou: venv\Scripts\activate  # Windows

# 3. Instalar dependências
# Para PRODUÇÃO (dependências fixas, reproduzível):
pip install -r requirements.lock

# Para DESENVOLVIMENTO (versões mais flexíveis):
pip install -r requirements.txt

# 4. Configurar ambiente
cp .env.example .env
# OBRIGATÓRIO: Configure GOOGLE_API_KEY de https://aistudio.google.com/app/apikey
# OPCIONAL: Configure PROJECT_PATH para especificar o repositório alvo

# 5. Build do índice RAG (primeira vez apenas, ~2 minutos)
python scripts/build_rag_index.py

# 6. Iniciar agente
python main.py
```

### Gerenciamento de Dependências

O projeto mantém dois arquivos de requisitos:

| Arquivo | Uso | Vantagens |
|---------|-----|-----------|
| `requirements.lock` | **Produção** e CI/CD | Versões exatamente fixadas, builds reproduzíveis |
| `requirements.txt` | **Desenvolvimento** | Versões com maior flexibilidade (>=), mais fácil adicionar/atualizar dependências |

**Fluxo Recomendado:**
- Produção: `pip install -r requirements.lock` — garante exatamente as versões testadas
- Dev: `pip install -r requirements.txt` — permite minor/patch updates automáticas

Para atualizar o lockfile após mudar requirements.txt:
```bash
pip freeze > requirements.lock
git add requirements.lock
git commit -m "chore: update lockfile"
```

---

## Configuração de Repositório

O agente pode ser direcionado para analisar diferentes repositórios através de três mecanismos:

### Método 1: Configuração estática via `.env`

Configure a variável `PROJECT_PATH` no arquivo `.env` com o caminho absoluto do repositório:

```env
# .env
GOOGLE_API_KEY=sua-chave-aqui
PROJECT_PATH=/Users/seu-usuario/Documentos/meu-projeto-python
# ou no Windows:
# PROJECT_PATH=C:\Users\seu-usuario\Documents\meu-projeto-python
```

Após editar `.env`, reinicie o agente:
```bash
python main.py
```

Todas as ferramentas operarão sobre o repositório especificado até uma nova configuração.

### Método 2: Clone dinâmico via interface de chat

Durante a execução, o usuário pode fornecer uma URL de repositório GitHub. A ferramenta `clone_repository` realiza o clone e atualiza automaticamente o contexto de análise sem necessidade de restart:

```
Entrada: "Analisa o repositório https://github.com/dbt-labs/jaffle_shop"

Saída: Repositório clonado com sucesso. PROJECT_PATH atualizado. 
       Todas as ferramentas agora operam em jaffle_shop.
```

Exemplos de repositórios para teste:
- `https://github.com/dbt-labs/jaffle_shop` (projeto de referência dbt)
- `https://github.com/apache/airflow` (framework de orquestração)

### Método 3: Troca de contexto durante sessão

Forneça uma URL diferente para mudar o repositório em análise:

```
Entrada: "Muda para https://github.com/apache/airflow"
Saída: Repositório clonado e carregado.
```

### Precedência de Configuração

| Precedência | Origem | Comportamento |
|---|---|---|
| 1 | `PROJECT_PATH` em `.env` | Repositório configurado na inicialização |
| 2 | URL fornecida via chat | Sobrescreve PROJECT_PATH durante sessão |

**Importante:** Você **deve** configurar um repositório. Sem configuração, o agente não funciona.

### Limite de Contexto por Análise

O Lupus limita o tamanho de arquivo lido em cada análise para evitar timeouts e excesso de uso de tokens. Padrão: **8000 bytes (8 KB)**.

Configure via variável de ambiente:
```bash
# Aumentar para análises maiores (ex: 20KB)
export LUPUS_MAX_CONTEXT_BYTES=20000

# Após definir, execute novamente
python main.py
```

**Trade-offs:**
| Limite | Vantagem | Desvantagem |
|--------|----------|------------|
| 8 KB (padrão) | ✓ Rápido, confiável | ✗ Contexto limitado |
| 16 KB | ✓ Mais contexto | ✗ Pode lentificar |
| 20+ KB | ✓ Análises maiores | ✗ Alto risco de timeout (>50KB gera warning) |

---

## Avaliação

O agente foi avaliado em 25 perguntas técnicas em 5 categorias usando um dataset de teste com scoring de LLM como juiz.

### Métricas Gerais

| Métrica | Valor |
|--------|-------|
| Acurácia | 96% (24/25) |
| Correspondência de Keywords | 85% |
| Cobertura de Ferramentas | 82% |
| Completude (juiz) | 4.8/5.0 |
| Relevância | 5.0/5.0 |
| Fundamentação | 5.0/5.0 |

### Análise por Categoria

| Categoria | Acurácia | Cobertura | Completude |
|----------|----------|----------------|--------------|
| Arquitetura | 100% | 100% | 5.0 |
| Módulos | 82% | 80% | 5.0 |
| Integração | 88% | 50% | 5.0 |
| Design | 81% | 80% | 4.8 |
| RAG | 76% | 100% | 4.4 |

### Executar Avaliação

```bash
python evaluation/run_evaluation.py
```

Os resultados são escritos em `evaluation/results.json`.

---

## LupusAPI — Camada HTTP

O Lupus também expõe o agente via REST API, construída com FastAPI. A interface HTTP mantém o mesmo núcleo do agente — `config.py`, tools, RAG — sem modificações, adicionando uma camada de transporte e observabilidade.

### Como rodar

```bash
# Instale as dependências da API (apenas uma vez)
pip install fastapi uvicorn[standard]

# Suba o servidor (da raiz do projeto)
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

Aguarde a mensagem `Application startup complete.` O startup leva ~5–10s (carrega o agente).

Documentação interativa disponível em `http://localhost:8000/docs` (Swagger UI).

### Endpoints

| Método | Endpoint | Descrição |
|---|---|---|
| `POST` | `/chat` | Envia mensagem ao agente; suporta `session_id` para histórico multi-turn |
| `GET` | `/tools` | Lista todas as 17 tools disponíveis com nome e descrição |
| `POST` | `/eval/run` | Executa avaliações automáticas via LangSmith SDK; retorna scores por evaluator |
| `GET` | `/health` | Status do servidor — `agent` e `langsmith` separados; retorna 503 se agente falhou |

### Exemplo rápido

```bash
# Conversar com o agente via HTTP
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Qual a arquitetura do projeto?", "session_id": "sessao-1"}'

# Verificar saúde do sistema
curl http://localhost:8000/health

# Avaliação rápida com 3 exemplos
curl -X POST http://localhost:8000/eval/run \
  -H "Content-Type: application/json" \
  -d '{"evaluators": ["all"], "max_examples": 3}'
```

### Observabilidade

Cada request gera um log com `request_id` único, método, path, status HTTP e latência:

```
INFO  request_id=a3f2b1c4  method=POST  path=/chat  status=200  latency_ms=4213.50  ip=127.0.0.1
```

O header `X-Request-ID` é injetado em todas as responses para correlacionar logs com erros.

Com `LANGCHAIN_TRACING_V2=true`, todas as chamadas ao agente aparecem automaticamente no dashboard LangSmith com traces de cada tool call.

### Avaliação via API

O endpoint `/eval/run` usa o LangSmith SDK para criar experimentos rastreáveis:

```
Dataset (chat_qa.jsonl, 20 exemplos)
    ↓
langsmith.evaluate(agente, evaluators=[correctness, tool_usage, latency])
    ↓
Experimento histórico em smith.langchain.com
```

Os evaluators medem: presença de keywords esperadas, cobertura de tools corretas, e latência convertida em score (0–1).

### ⚠️ Contexto e limitações

O Lupus é um **projeto de aprendizado**. A LupusAPI foi construída para explorar FastAPI, injeção de dependência assíncrona, e integração com o SDK do LangSmith — não para ser um produto em produção.

A API não tem autenticação. Isso é intencional para manter o escopo focado no que o projeto se propõe a ensinar. Qualquer pessoa com acesso à rede pode chamar os endpoints — o que é aceitável num ambiente local de desenvolvimento, mas não num contexto público ou de cliente real.

Documentação completa do módulo: [`api/README.md`](api/README.md).

---

## Motivação e Abordagem

Análise de repositórios em escala apresenta desafios:
- Documentação diverge rapidamente da implementação
- Onboarding requer grande investimento de tempo
- Arquiteturas complexas demandam compreensão precisa e em tempo real

Lupus aborda esses desafios através de:
- **Respostas fundamentadas**: Todas as respostas derivam do código real do repositório
- **Sem APIs externas**: Busca semântica local preserva privacidade de dados
- **Documentação automática**: Gera documentação técnica atual e precisa
- **Agnóstico a stack**: Opera com dbt, Python, Node.js, Terraform, Kubernetes, etc.
- **Arquitetura extensível**: Ferramentas são modulares e independentemente testáveis
- **Validado empiricamente**: 96% de acurácia em dataset de perguntas técnicas

---

## Blocos de Desenvolvimento

| Bloco | Descrição |
|-------|-----------|
| 1 | Setup de ambiente, DeepAgents, integração Gemini |
| 2 | Ferramentas de discovery (detecção de stack, exploração) |
| 3 | Ferramentas de domínio e orquestração de agentes |
| 4 | Persona (SKILL.md), interface CLI |
| 5 | Geração de documentação |
| 6 | Avaliação quantitativa (25 perguntas, LLM como juiz) |
| 7 | Polish (README, requirements, organização) |
| 8 | Pipeline RAG (FAISS + BM25 + RRF + CrossEncoder) |
| 9 | LupusAPI Fase 1 — FastAPI, Swagger, endpoints mock, schemas Pydantic |
| 10 | LupusAPI Fase 2 — Integração agente real, session_id, tratamento de erros |
| 11 | LupusAPI Fase 3 — LangSmith evals dataset + evaluators + POST /eval/run |
| 12 | LupusAPI Fase 4 — Logging middleware, GET /health, .env.example, README |

---

## Troubleshooting

### Agente congela ou não responde

**Sintoma:** Lupus fica travado ao fazer uma pergunta.

**Causas e Soluções:**

1. **Contexto do repositório muito grande**
   - O agente limita análises a 8KB de conteúdo para evitar timeouts
   - Solução: Faça perguntas mais específicas
   - Exemplo: Ao invés de "analise tudo", tente "qual a estrutura do Bronze?"

2. **Timeout de 3 minutos atingido**
   - O agente tem limite de 180s para responder
   - Solução: 
     - Tente novamente com pergunta mais simples
     - Mude de repositório com `/repo <URL>`
     - Se usar busca semântica, rode `python scripts/build_rag_index.py` para reindexar

3. **Índice RAG desatualizado**
   - Se clonou um repositório novo, o índice FAISS pode estar desincronizado
   - Solução: `python scripts/build_rag_index.py`
   - O agente avisa quando detecta mismatch

### HuggingFace model download trava

**Sintoma:** Primeira execução fica presa ao baixar modelos de embeddings.

**Causa:** Conexão instável com HuggingFace hub ou timeout de download.

**Solução:**
- Aguarde até 5 minutos (primeiro download baixa ~380MB)
- Se timeout persistir, defina variável de ambiente:
  ```bash
  export HF_HUB_DOWNLOAD_TIMEOUT=600
  ```

### RAG warnings aparecem

**Sintoma:** "O índice RAG está desatualizado para este repositório"

**Causa:** Você clonou um repositório novo, mas o índice FAISS ainda é de outro repo.

**Solução:**
```bash
python scripts/build_rag_index.py
```

O agente detecta automaticamente e avisa quando isso acontece.

### Erro ao clonar repositório

**Sintoma:** "git clone falhou"

**Causas:**
- URL inválida ou repositório privado (Lupus acessa apenas repos públicos)
- Sem conexão com GitHub

**Solução:**
- Verifique se a URL é pública e válida
- Teste em outro terminal: `git clone <URL>`

### Problema ao ler arquivo

**Sintoma:** "Arquivo não encontrado" ao usar `analyze_code`

**Causa:** Caminho do arquivo está fora do repositório configurado.

**Solução:**
- Use caminhos relativos: `models/silver/arquivo.sql` (não caminho absoluto)
- Confirme se o arquivo existe no repo com `/repo` info

### DeepAgents não instala

**Sintoma:** "deepagents not found" ou erro de instalação.

**Solução:**
1. Confirme Python 3.11+: `python --version`
2. Upgrade pip: `pip install --upgrade pip`
3. Instale deepagents 0.5.0+: `pip install deepagents==0.5.0a2`

Se ainda falhar, crie venv nova:
```bash
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

---

---

## Learn More

| Documento | Conteúdo |
|-----------|----------|
| [AGENTS.md](AGENTS.md) | Contexto e persona do agente — quando usar cada ferramenta |
| [TOOLS.md](TOOLS.md) | Referência completa das 17 ferramentas com parâmetros e exemplos |
| [SKILL.md](skills/lupus/SKILL.md) | Definição de persona, tom, limites e regras de comportamento |
| [MAINTENANCE.md](MAINTENANCE.md) | Guia para contributors — trocar LLM, modificar comportamento |
| [api/README.md](api/README.md) | Como rodar a REST API (FastAPI + Swagger) |
| [tests/README.md](tests/README.md) | Suite de testes (pytest) e como adicionar novos |

---

## Licença

Projeto acadêmico para fins educacionais e de pesquisa.

**Tecnologias:**
- **LLM:** Flexível — Gemini 2.5 Flash (padrão), Claude, OpenAI, ou compatível OpenAI via `LLM_PROVIDER`
- **Framework de agentes:** DeepAgents + LangChain + LangGraph
- **RAG:** FAISS (busca semântica) + BM25 (busca keyword) + CrossEncoder (reranking)
- **Observabilidade:** LangSmith (opcional, via `LANGCHAIN_TRACING_V2`)
