# 🔍 Lupus — AI Code Intelligence Agent

**Analisa qualquer repositório técnico via conversa natural.** Faça perguntas técnicas como se estivesse conversando com um especialista — o Lupus consulta o código real, nunca inventa.

Configure qual repositório analisar de 3 formas:
- **`.env`**: defina `PROJECT_PATH` para um repositório local
- **Link no chat**: mande um link GitHub e o Lupus clona na hora
- **Padrão**: analisa o projeto SRAG incluído

Desenvolvido como projeto acadêmico com [DeepAgents](https://github.com/deepagents) (LangChain/LangGraph) + Gemini 2.5 Flash.

## O que faz

Lupus é um agente conversacional especializado que responde perguntas técnicas sobre repositórios. Não usa conhecimento geral — consulta os arquivos reais do projeto via 17 tools especializadas. Tudo o que ele diz é fundamentado no código.

**Exemplos de perguntas que Lupus responde:**
```
💬 "Qual a arquitetura do projeto?"
💬 "Como a coluna X se transforma em Y?"
💬 "Quais são as dependências externas?"
💬 "Gera documentação da arquitetura"
💬 "Analisa o repositório github.com/dbt-labs/jaffle_shop"
```

### 17 Tools Especializadas

**Discovery** (5) — mapeamento automático:
- Detecta stack tecnológico (dbt, Node.js, Go, Java, Terraform, K8s, Docker, notebooks)
- Explora estrutura de arquivos com secret scan
- Lê dados (CSV, JSON, Parquet, Excel)
- Clona repositórios GitHub na hora

**Análise de Domínio** (7) — lê arquivos reais:
- Arquitetura: Medallion Architecture, módulos, fluxo de dados
- dbt: Bronze/Silver/Gold, transformações, SQL, testes
- Linhagem de dados: rastreamento completo fonte → camadas
- Pipeline: DABs, schedule, deploy, orquestração
- Dicionário de dados: colunas, tipos, descrições por camada
- Dependências: grafo de imports (Python/JS/TS/Go), libs externas
- Especificação de agentes: tools, guardrails, integrações

**Sub-agents** (4) — análise profunda:
- Análise de código: leitura e explicação de arquivos
- **Documentação automática**: gera Markdown do repositório
- Review de arquitetura: análise crítica de decisões técnicas
- Sugestões de melhoria: análise baseada em evidências

**RAG** (1) — busca semântica:
- Busca no código via hybrid search (FAISS + BM25 + RRF + CrossEncoder)
- Encontra respostas sem saber o arquivo exato

## ✨ Lupus se auto-documenta

Lupus não é só um analisador — **ele gera documentação**. Você pode pedir:

```
💬 "Gera documentação completa da arquitetura"
💬 "Cria um diagrama em Markdown da linhagem de dados"
💬 "Documenta as 5 principais transformações do dbt"
```

E o Lupus gera arquivos **Markdown profissionais** que explicam o repositório. Porque às vezes o melhor jeito de entender um projeto é **já tendo documentação bem feita**.

---

## Arquitetura

### Fluxo de uma pergunta

```mermaid
flowchart TD
    User(["👤 Usuário"])
    User -->|pergunta| CLI

    subgraph CLI["CLI — main.py"]
        Rich["Rich\nspinner · markdown · panels"]
    end

    CLI -->|invoke| MW

    subgraph AgentCore["Agent — LangGraph  ·  config.py"]
        direction TB

        subgraph MW["Middleware Stack  (injeção de contexto)"]
            direction LR
            SK["SkillsMiddleware\nSKILL.md → persona Lupus (especialista técnico)"]
            ME["MemoryMiddleware\nAGENTS.md → contexto macro"]
            FS["FilesystemMiddleware\nacesso virtual a srag_agent/"]
            PT["PatchToolCallsMW\ncorrige formato Gemini"]
            TD["TodoListMiddleware\nrastreia subtarefas"]
        end

        LLM["🤖 Gemini 2.5 Flash\nraciocínio · tool selection · síntese"]
        MW -->|contexto enriquecido| LLM
    end

    LLM -->|tool call| Tools

    subgraph Tools["Tools  (17 total)"]
        direction LR

        subgraph DISC["Discovery  ×5  —  mapeiam o repositório"]
            direction TB
            D1["discover_project\ndetecta stack tecnológico"]
            D2["explore_repository\nárvore anotada + secret scan"]
            D3["read_data_file\nlê CSV · JSON · Parquet"]
            D4["clone_repository\nclona do GitHub · troca PROJECT_PATH"]
            D5["analyze_full_repository\nclone + explore + leitura automática"]
        end

        subgraph DT["Domain Tools  ×7  —  leem arquivos reais"]
            direction TB
            T1["get_project_architecture"]
            T2["analyze_dbt_model"]
            T3["map_data_lineage"]
            T4["get_agent_tools_spec"]
            T5["analyze_pipeline_config"]
            T6["get_data_dictionary"]
            T7["map_code_dependencies"]
        end

        subgraph SA["Sub-agents  ×4  —  LLM interno"]
            direction TB
            S1["analyze_code\nlê arquivos do projeto"]
            S2["generate_documentation\ngera Markdown"]
            S3["review_architecture\nanálise crítica"]
            S4["suggest_improvements\nsugestões priorizadas"]
        end

        subgraph RAG["RAG  ×1  —  busca semântica"]
            SC["search_codebase\nhybrid search no codebase"]
        end
    end

    Tools -->|resultado| LLM
    LLM -->|resposta final| CLI
    CLI -->|output formatado| User

    AgentCore -. "traces automáticos\n(LANGCHAIN_TRACING_V2=true)" .-> LS["📊 LangSmith\nobservabilidade"]
```

---

### Pipeline RAG — como `search_codebase` funciona internamente

```mermaid
flowchart LR
    SragAgent["srag_agent/\n.sql · .yml · .ipynb · .md"]
    Script["scripts/build_rag_index.py\n(roda offline, uma vez)"]
    SragAgent --> Script

    subgraph Indexer["rag/indexer.py  —  build-time"]
        direction TB
        Chunk["Chunking semântico\nsql → 1 arquivo/chunk\nyml → 1 arquivo/chunk\nipynb → 1 célula/chunk\nmd → 1 seção ##/chunk"]
        Embed["Embeddings\nall-MiniLM-L6-v2\n384 dims · local · sem API"]
        Build["FAISS IndexFlatIP\n+ normalize_L2\n= cosine similarity exata"]
        Chunk --> Embed --> Build
    end

    Script --> Indexer

    subgraph Index["rag/index/  (gitignored)"]
        direction TB
        FI["srag.index\n(vetores FAISS)"]
        MD["srag_metadata.json\ncontent · file_path · layer\nchunk_type · model_name"]
    end

    Indexer --> Index

    Query(["query + layer\n(ex: 'como obito_srag_flag é criada'\nlayer='silver')"])

    subgraph Retriever["rag/retriever.py  —  query-time"]
        direction TB
        SemanticSearch["🔍 FAISS Semantic Search\nencode query → normalize\n→ top-15 por cosine sim"]
        KeywordSearch["🔑 BM25 Keyword Search\ntokenize query\n→ top-15 por BM25Okapi"]
        RRF["🔀 Reciprocal Rank Fusion\nscore = Σ 1 ÷ (60 + rank)\nmerge → top-15 candidatos"]
        Reranker["🎯 CrossEncoder Reranker\nms-marco-MiniLM-L-6-v2\n(query, chunk) juntos → score preciso"]
        Top5["Top-5 chunks\ncom source attribution\n[rank] filepath · camada: layer"]
        SemanticSearch --> RRF
        KeywordSearch --> RRF
        RRF --> Reranker
        Reranker --> Top5
    end

    Index --> Retriever
    Query --> Retriever
    Top5 --> Agent(["🤖 Gemini 2.5 Flash\nsintetiza resposta"])
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
| "O que faz o silver_srag_data.sql?" | `analyze_dbt_model` |
| "Como os dados fluem do Bronze ao Gold?" | `map_data_lineage` |
| "Qual o schedule do pipeline?" | `analyze_pipeline_config` |
| "Quais colunas tem na Gold?" | `get_data_dictionary` |
| "Como o ai_agent usa o LLM?" | `get_agent_tools_spec` |
| "Quais módulos esse projeto importa mais?" | `map_code_dependencies` |
| "Leia o arquivo X para mim" | `analyze_code` |
| "Gere documentação da arquitetura" | `generate_documentation` |
| "Por que usaram ephemeral na Bronze?" | `review_architecture` |
| "Quais melhorias você sugere pro projeto?" | `suggest_improvements` |
| "Como `obito_srag_flag` é criada no SQL?" | `search_codebase` |

## 🛠️ Stack Tecnológico

| Componente | Tecnologia | Por quê? |
|---|---|---|
| **Framework** | DeepAgents (LangChain + LangGraph) | Agentes com stateful memory e middleware customizável |
| **LLM** | Gemini 2.5 Flash (Google AI) | Rápido, barato, excelente pra tool-calling |
| **RAG** | FAISS + BM25 + RRF (local, sem API) | Busca semântica híbrida offline, seguro pra dados sensíveis |
| **CLI** | Rich | Markdown, panels, spinners — output profissional no terminal |
| **Persona** | SKILL.md → SkillsMiddleware | Instruções contextualizadas, tom consistente |
| **Persistência** | SQLite (conversas) | Multi-turn memory, sem perder histórico |
| **Observabilidade** | LangSmith (opcional) | Tracing automático, debug de chamadas |
| **Demo** | SRAG (Databricks + dbt + Llama) | Projeto real, complexo, bem documentado |

**Escolhas de design:**
- ✅ **Sem API externa pra RAG** — FAISS é offline, dados nunca saem do computador
- ✅ **Contexto real** — tools consultam arquivos reais, não usam knowledge cutoff
- ✅ **Modular** — cada tool é independente, fácil de estender
- ✅ **Documentado** — o próprio Lupus gera documentação

## 📁 Estrutura do Projeto

```
lupus/
├── 🎯 ENTRYPOINT
│   ├── main.py                    # Chat interativo (CLI)
│   ├── config.py                  # Configuração central (LLM, tools, middlewares)
│   └── .env.example               # Template — configure PROJECT_PATH e GOOGLE_API_KEY aqui
│
├── 🧠 AGENTE
│   ├── core/
│   │   ├── context_manager.py     # Gerencia repo ativo, dispara hooks
│   │   └── repo_context.py        # Estado do repositório (path, cache, RAG)
│   └── skills/lupus/SKILL.md      # Persona, tom, limites (lido automaticamente)
│
├── 🔧 17 TOOLS (Discovery + Domain + Sub-agents + RAG)
│   ├── tools/__init__.py          # Exporta todas as 17 tools
│   ├── tools/project_discovery.py # Stack detection (dbt, Node, Go, etc)
│   ├── tools/repository_explorer.py # File tree + secret scan
│   ├── tools/github_integration.py # Clone de repos GitHub
│   ├── tools/architecture.py      # Análise de arquitetura
│   ├── tools/dbt_analyzer.py      # Bronze/Silver/Gold, SQL
│   ├── tools/lineage.py           # Data lineage (fluxo de dados)
│   ├── tools/pipeline_analyzer.py # DAB schedule, deploy
│   ├── tools/data_dictionary.py   # Schema, colunas, testes
│   ├── tools/code_dependencies.py # Grafo de imports
│   ├── tools/subagents.py         # analyze_code, generate_documentation, review, suggest
│   ├── tools/rag_search.py        # Busca semântica híbrida (FAISS + BM25 + RRF)
│   └── tools/cache.py             # Cache TTL compartilhado
│
├── 🔍 RAG (Busca Semântica)
│   ├── rag/indexer.py             # Chunking + FAISS builder
│   ├── rag/retriever.py           # Hybrid search + reranker
│   └── rag/index/                 # Índices gerados (gitignored)
│
├── 🧪 TESTES & AVALIAÇÃO
│   ├── tests/                     # 26 testes de integração (discovery + domain + persona)
│   ├── evaluation/
│   │   ├── dataset.json           # 25 perguntas técnicas
│   │   └── run_evaluation.py      # Avaliação com LLM-as-judge (96% accuracy)
│   └── scripts/
│       ├── build_rag_index.py     # Build offline do índice RAG
│       └── generate_docs.py       # Gera 5 docs de referência
│
├── 📚 DOCS
│   ├── docs/                      # Documentação de desenvolvimento (8 blocos)
│   ├── README.md                  # Este arquivo
│   └── AGENTS.md                  # Contexto macro do agente
│
└── 📦 PROJETO DEMO
    └── srag_agent/                # Projeto SRAG real (Databricks + dbt + Llama)
```

**Fluxo de dados:**
```
main.py → config.make_agent() → LangGraph
   ↓
Middleware Stack (Skills, Memory, Filesystem, Patch)
   ↓
Gemini 2.5 Flash (LLM)
   ↓
Invoca tools conforme necessário → tools/ (17 total)
   ↓
RAG busca (se pergunta sobre código) → rag/
   ↓
Resposta formatada (Rich) → usuário
```

## 🚀 Setup (5 minutos)

```bash
# 1. Clone
git clone https://github.com/seu-usuario/lupus.git
cd lupus

# 2. Ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou: venv\Scripts\activate  # Windows

# 3. Dependências
pip install -r requirements.txt

# 4. Variáveis de ambiente
cp .env.example .env
# OBRIGATÓRIO: adicione GOOGLE_API_KEY (get em https://aistudio.google.com/app/apikey)
# OPCIONAL: configure PROJECT_PATH para seu repositório

# 5. Build do índice RAG (primeira vez, ~2 min)
python scripts/build_rag_index.py

# 6. Rodar
python main.py
```

**Pronto!** Lupus está rodando. Comece com:
```
💬 Qual a arquitetura do projeto?
💬 Quais tecnologias são usadas?
💬 Analisa github.com/dbt-labs/jaffle_shop
```

---

## 🎯 Como escolher qual repositório analisar?

Por padrão, Lupus analisa o projeto **SRAG** incluído aqui. Mas você pode analisar **qualquer repositório** — local, remoto, público ou privado (se você tem acesso).

### Opção 1: Repositório local (configure no `.env`)

Edite o `.env` e descomente/complete a linha `PROJECT_PATH`:

```env
# .env
GOOGLE_API_KEY=sua-chave-aqui

# Escolha seu repositório
PROJECT_PATH=/Users/seu-usuario/Documentos/meu-projeto-python
# PROJECT_PATH=C:\Users\seu-usuario\Documentos\meu-projeto-python  (Windows)
```

Depois **reinicie Lupus**:
```bash
python main.py
```

A partir daí, **todas as tools analisam seu repositório**. Sem necessidade de configuração extra.

### Opção 2: Link do GitHub (clonar na hora, sem restart)

**Sem restart!** Enquanto Lupus está rodando, peça para clonar:

```
💬 Analisa github.com/dbt-labs/jaffle_shop

🤖 Clonando jaffle_shop... ✓
   Descobrindo stack... ✓
   
   Repositório clonado com sucesso!
   PROJECT_PATH atualizado. Todas as tools agora analisam este repositório.

💬 Qual a arquitetura do projeto?

🤖 (Analisa jaffle_shop sem precisar reiniciar)
```

**Repositórios legais para testar:**
- `https://github.com/dbt-labs/jaffle_shop` — dbt clean room, perfect para começar
- `https://github.com/apache/airflow` — orchestration, complexo
- Qualquer repositório seu ou de open source que queira analisar

### Opção 3: Trocar entre repositórios durante a conversa

```
💬 Muda para https://github.com/apache/airflow

🤖 Clonando airflow... ✓

💬 Quais as principais tasks do pipeline?

🤖 (Agora analisa Airflow)
```

### Resumo: qual usar?

| Cenário | Use |
|---------|-----|
| Analisar sempre o mesmo repo | **Opção 1** — configure `PROJECT_PATH` no `.env` |
| Testar vários repos | **Opção 2** — clone via chat (mais fácil, sem restart) |
| Mudar de repo na conversa | **Opção 3** — dinâmico, instantâneo |
| Nada configurado | **Padrão** — analisa `./srag_agent` (projeto SRAG) |

---

## 📊 Avaliação Quantitativa

Lupus foi testado com 25 perguntas técnicas sobre o projeto SRAG. Resultados:

**Métricas Gerais:**
| Métrica | Resultado |
|---------|-----------|
| **Accuracy** | **96%** ✓ (24/25 perguntas corretas) |
| Keyword accuracy | 85% |
| Tool coverage | 82% |
| Completude (nota de juiz) | 4.8/5.0 |
| **Relevância** | **5.0/5.0** ✓ |
| **Fundamentação** | **5.0/5.0** ✓ |

**Por categoria:**
| Categoria | Acurácia | Cobertura | Completude |
|-----------|---------|-----------|------------|
| Arquitetura | 100% | 100% | 5.0 |
| Módulos | 82% | 80% | 5.0 |
| Integração | 88% | 50% | 5.0 |
| Design | 81% | 80% | 4.8 |
| RAG | 76% | 100% | 4.4 |

**Rodas avaliação você mesmo:**
```bash
python evaluation/run_evaluation.py
```

Resultados são salvos em `evaluation/results.json`.

## Blocos de desenvolvimento

| Bloco | Descrição|
|---|---|
| 1 | Setup: ambiente, DeepAgents, Gemini |
| 2 | Domain Tools: 6 ferramentas de domínio |
| 3 | Agent: integração LangGraph + middleware + sub-agents |
| 4 | Skill + CLI: Lupus persona + chat interativo |
| 5 | Documentação: 5 docs gerados automaticamente |
| 6 | Avaliação: 25 perguntas, 3 níveis de métricas, 96% accuracy |
| 7 | Polish: README, requirements, organização, git |
| 8 | RAG: hybrid search (FAISS + BM25 + RRF), embeddings locais |

## ❓ Por que Lupus?

**Problema:** Documentação de código fica desatualizada. Onboarding é lento. Entender uma arquitetura grande requer horas de leitura.

**Solução:** Um agente que lê código real em tempo real e explica com precisão.

**Diferencial:**
- ✅ Consulta arquivos reais, nunca inventa
- ✅ Sem API externa pra RAG (dados sensíveis ficam locais)
- ✅ Gera documentação automática (Markdown profissional)
- ✅ Funciona com qualquer repositório (dbt, Python, Node, Terraform, K8s...)
- ✅ Modular (fácil estender com novas tools)
- ✅ Testado quantitativamente (96% accuracy)

---

## 🎓 Licença

Projeto acadêmico — uso educacional e pesquisa.

**Built with:**
- 🤖 Gemini 2.5 Flash
- 🔗 DeepAgents (LangChain + LangGraph)
- 🔍 FAISS + BM25 (busca local)
- 📊 LangSmith (observabilidade opcional)
