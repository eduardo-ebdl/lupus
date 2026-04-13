"""LupusAPI — Ponto de entrada do servidor FastAPI.

Como o FastAPI gera o Swagger automaticamente?
-----------------------------------------------
Quando você instancia `FastAPI()`, o framework registra internamente
todos os endpoints, seus schemas (Pydantic) e metadados (summary, description).
Com isso, ele gera automaticamente dois formatos de documentação:

  - /docs  → Swagger UI (interativo, dá pra testar os endpoints direto)
  - /redoc → ReDoc (mais formal, melhor para leitura)

Nenhum arquivo YAML/JSON precisa ser escrito manualmente.
O Pydantic é que "informa" ao OpenAPI quais campos cada endpoint aceita/retorna.

Por que separar `create_app()` de `if __name__ == "__main__"`?
---------------------------------------------------------------
Isso segue o padrão Application Factory, comum em Flask/FastAPI.
Tendo uma função que cria o app (não apenas `app = FastAPI()` no módulo),
os testes podem importar `create_app()` e criar instâncias isoladas
sem efeitos colaterais no import.
"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routers import chat, tools, eval, health
from api.middleware import LoggingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gerencia o ciclo de vida da aplicação: setup → serve → teardown.

    Por que criar o agente aqui e não dentro de cada endpoint?
    -----------------------------------------------------------
    Criar o agente é caro: carrega sentence-transformers (~500ms),
    abre conexão SQLite, inicializa todos os middlewares LangGraph.

    Se criássemos em cada request, a primeira mensagem de cada sessão
    levaria meio segundo a mais, e o servidor ficaria instável sob carga.

    A solução: criamos UMA instância no startup e armazenamos em
    `app.state.agent`. O FastAPI garante que `app.state` é thread-safe
    para leituras concorrentes.

    Sessões diferentes são isoladas pelo `thread_id` do LangGraph —
    não precisam de instâncias separadas do agente.
    """
    # --- STARTUP ---
    import logging
    logger = logging.getLogger(__name__)
    logger.info("🐺 LupusAPI iniciando — carregando agente Lupus...")

    # make_agent() é síncrono e pesado; rodamos em thread para não
    # bloquear o event loop durante o startup
    from config import make_agent
    app.state.agent = await asyncio.to_thread(make_agent)

    logger.info("🐺 Agente Lupus pronto.")
    yield
    # --- SHUTDOWN ---
    # Aqui fecharíamos conexões, caches, etc.
    # O SQLite do LangGraph fecha via atexit registrado em config.py.
    logger.info("🐺 LupusAPI encerrando.")


def create_app() -> FastAPI:
    """Cria e configura a instância FastAPI com todos os routers."""
    app = FastAPI(
        title="LupusAPI",
        version="0.1.0",
        description=(
            "API HTTP sobre o agente Lupus — AI Code Intelligence.\n\n"
            "## Endpoints\n"
            "- **POST /chat** — Conversar com o agente Lupus\n"
            "- **GET /tools** — Listar todas as ferramentas disponíveis\n"
            "- **POST /eval/run** — Executar avaliações LangSmith\n\n"
            "## Autenticação\n"
            "Nenhuma nesta versão (ambiente local de desenvolvimento)."
        ),
        lifespan=lifespan,
        # Customiza as URLs da documentação (padrão já é /docs e /redoc)
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS: permite que UIs rodando em outras origens chamem esta API.
    # Em produção, trocar allow_origins por domínios específicos.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # TODO(produção): Autenticação não implementada.
    # Esta API não tem controle de acesso — qualquer cliente com acesso à rede
    # pode chamar todos os endpoints, incluindo /eval/run (que consome créditos LLM).
    #
    # Para expor além do ambiente local, adicione uma das opções abaixo:
    #   1. API Key simples:   instale `pip install fastapi-simple-security`
    #   2. JWT/OAuth2:        ver fastapi.tiangolo.com/tutorial/security/
    #   3. Proxy com auth:   Nginx/Traefik com middleware de autenticação externo
    #
    # Referência: https://fastapi.tiangolo.com/tutorial/security/

    # Logging estruturado: loga cada request com request_id e latência.
    # Adicionado após o CORS para que o request_id apareça em todos os logs.
    # Ordem importa: middlewares são executados na ordem INVERSA de registro
    # (o último adicionado é o primeiro a interceptar a request).
    app.add_middleware(LoggingMiddleware)

    # Registra os routers — cada um traz seus endpoints e prefixo
    app.include_router(chat.router)
    app.include_router(tools.router)
    app.include_router(eval.router)
    app.include_router(health.router)

    # Endpoint raiz simples — útil para health check básico
    @app.get("/", tags=["Root"], summary="Status da API")
    async def root():
        return {
            "name": "LupusAPI",
            "version": "0.1.0",
            "status": "online",
            "docs": "/docs",
        }

    return app


# Instância global — usada pelo Uvicorn:
#   uvicorn api.main:app --reload
app = create_app()


if __name__ == "__main__":
    import os
    import uvicorn

    # Isso só executa quando rodamos `python api/main.py` diretamente.
    # O modo recomendado é via CLI: uvicorn api.main:app --reload
    uvicorn.run(
        "api.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=os.getenv("API_RELOAD", "true").lower() == "true",
        log_level=os.getenv("API_LOG_LEVEL", "info"),
    )
