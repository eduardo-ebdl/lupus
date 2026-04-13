# LupusAPI

Camada HTTP sobre o agente Lupus — expõe via REST os mesmos recursos disponíveis no CLI.

## Pré-requisitos

```bash
# No virtualenv do projeto lupus:
pip install fastapi uvicorn[standard]
```

Todas as outras dependências (`langsmith`, `langgraph`, `sentence-transformers`) já fazem parte do `pyproject.toml`.

## Como rodar

```bash
# Da raiz do projeto lupus/
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

O servidor sobe em `http://localhost:8000`.

### ⚠️ Aviso de Segurança

Se já há algo rodando na porta 8000, mude a porta:

```bash
uvicorn api.main:app --reload --port 9000
# Acesse em http://localhost:9000
```

**A API não tem autenticação.** Se exposta publicamente, qualquer pessoa pode acessá-la. Use apenas em ambientes locais ou com um proxy reverso (nginx) com autenticação.

> **Hot-reload**: `--reload` detecta mudanças nos arquivos e reinicia automaticamente.  
> Para desenvolvimento local é seguro. Para qualquer outra coisa, não exponha a porta 8000 publicamente.

## Documentação interativa

| URL | Descrição |
|---|---|
| `http://localhost:8000/docs` | Swagger UI — teste os endpoints direto no browser |
| `http://localhost:8000/redoc` | ReDoc — documentação mais formal |
| `http://localhost:8000/openapi.json` | Schema OpenAPI 3.1 em JSON |

## Endpoints

### `POST /chat`

Envia uma mensagem para o agente Lupus e recebe a resposta.

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Qual a arquitetura do projeto?", "session_id": "minha-sessao-123"}'
```

**Body:**
```json
{
  "message": "string",         // obrigatório — pergunta para o agente
  "session_id": "string"       // opcional — mantém histórico entre chamadas
}
```

**Response (200 OK):**
```json
{
  "response": "A arquitetura segue o padrão Medallion...",
  "tools_used": ["get_project_architecture"],
  "latency_ms": 4213.5,
  "session_id": "minha-sessao-123"
}
```

> `session_id` funciona como o `thread_id` do LangGraph — conversas com o mesmo ID compartilham histórico.

#### Exemplo: Conversa Multi-Turn

```bash
# Mensagem 1 — análise inicial
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Analisa https://github.com/dbt-labs/jaffle_shop",
    "session_id": "session-abc123"
  }'

# Response: Stack detectada, arquitetura descrita

---

# Mensagem 2 — follow-up (mesmo session_id)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Como é feita a linhagem de dados?",
    "session_id": "session-abc123"
  }'

# Response: Agent já tem contexto do jaffle_shop, responde sobre linhagem
```

#### Respostas de Erro

**HTTP 400** — Bad Request (input inválido):
```json
{
  "detail": "message field is required"
}
```

**HTTP 500** — Internal Server Error (agente falhou):
```json
{
  "detail": "Agent crashed during execution",
  "request_id": "xyz789"
}
```

**HTTP 503** — Service Unavailable (agente não inicializou):
```json
{
  "detail": "Agent not available",
  "status": "degraded"
}
```

---

### `GET /tools`

Lista todas as ferramentas disponíveis para o agente.

```bash
curl http://localhost:8000/tools
```

---

### `POST /eval/run`

Executa avaliações automáticas via LangSmith SDK.

```bash
curl -X POST http://localhost:8000/eval/run \
  -H "Content-Type: application/json" \
  -d '{"evaluators": ["all"], "max_examples": 5}'
```

**Body:**
```json
{
  "evaluators": ["all"],        // ou ["correctness", "tool_usage", "latency"]
  "dataset_name": "lupus-chat-qa", // padrão
  "max_examples": 5             // opcional — limita para teste rápido
}
```

> ⚠️ Esta operação chama o agente para cada exemplo do dataset. Pode levar vários minutos.  
> Os resultados aparecem no dashboard: [smith.langchain.com](https://smith.langchain.com)

---

### `GET /health`

Verifica o status do servidor e seus componentes.

```bash
curl http://localhost:8000/health
```

**Response (tudo ok):**
```json
{
  "status": "ok",
  "version": "0.1.0",
  "components": {
    "agent": {"status": "ok"},
    "langsmith": {"status": "ok"}
  }
}
```

Retorna **HTTP 200** se tudo operacional (ou degradado), **HTTP 503** se o agente falhou na inicialização.

---

## Estrutura do módulo

```
api/
├── main.py              # Ponto de entrada (create_app, lifespan)
├── middleware.py        # Logging estruturado (request_id, latência)
├── dependencies.py      # Dependency Injection (get_agent)
├── routers/
│   ├── chat.py          # POST /chat
│   ├── tools.py         # GET /tools
│   ├── eval.py          # POST /eval/run
│   └── health.py        # GET /health
├── schemas/
│   ├── chat.py          # ChatRequest, ChatResponse
│   ├── tools.py         # ToolInfo, ToolsResponse
│   └── eval.py          # EvalRequest, EvalResponse
└── services/
    ├── agent_service.py # Bridge assíncrona → agente Lupus
    └── eval_service.py  # Integração com LangSmith SDK
```

## API vs CLI — Quando Usar Cada Uma

| Cenário | CLI | API |
|---------|-----|-----|
| Uso local, interativo | ✅ Preferido | ❌ Overhead desnecessário |
| Integração em aplicação Python | ❌ Subprocess é frágil | ✅ Chame direto a config.py |
| Integração em aplicação externa (JavaScript, Go, etc) | ❌ Não funciona | ✅ Ideal |
| Exposição para múltiplos usuários | ❌ 1 processo por usuário | ✅ 1 servidor, múltiplos clients |
| Testing/automação de análises | ⚠️ Possível via subprocess | ✅ Preferido (request idempotente) |
| Baixa latência (<5s) | ✅ Direto | ⚠️ Overhead de HTTP |

**Recomendação:** 
- **Desenvolvimento local:** CLI
- **Produção / múltiplos usuários:** API
- **Integração com outro sistema:** API

---

## Variáveis de ambiente relevantes para a API

| Variável | Padrão | Descrição |
|---|---|---|
| `LANGCHAIN_API_KEY` | — | Chave LangSmith (habilita `/eval/run` e tracing) |
| `LANGCHAIN_TRACING_V2` | `false` | Ativa tracing automático de todas as calls |
| `LANGCHAIN_PROJECT` | `lupus` | Projeto no dashboard LangSmith |
| `LLM_PROVIDER` | `gemini` | Provider do LLM usado pelo agente |
| `GOOGLE_API_KEY` | — | Chave da API Gemini (se LLM_PROVIDER=gemini) |

Veja `.env.example` para a lista completa com descrições.

## Observabilidade

### Logs de acesso

Cada request gera um log com `request_id`, método, path, status e latência:

```
INFO  request_id=a3f2b1c4 method=POST path=/chat status=200 latency_ms=4213.50 ip=127.0.0.1
WARN  request_id=d9e1a7f2 method=POST path=/chat status=500 latency_ms=312.10 ip=127.0.0.1
```

O header `X-Request-ID` é injetado em todas as responses — útil para correlacionar logs com erros reportados.

### LangSmith Tracing

Com `LANGCHAIN_TRACING_V2=true`, todas as chamadas ao agente (via `/chat` ou `/eval/run`) aparecem automaticamente no dashboard LangSmith com:
- Input / output completos
- Quais tools foram chamadas e com quais argumentos
- Latência por etapa do agente
- Link para o experimento de avaliação (quando via `/eval/run`)
