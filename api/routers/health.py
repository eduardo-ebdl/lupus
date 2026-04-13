"""Router do endpoint GET /health.

O que um health check deve e não deve expor:
--------------------------------------------
DEVE:
  - Dizer se o servidor está vivo e pronto para receber requests
  - Indicar se dependências críticas estão operacionais (agente, LangSmith)
  - Retornar em < 100ms (se demorar muito, o próprio health check falhou)

NÃO DEVE:
  - Expor detalhes internos para o mundo (stack traces, chaves, paths)
  - Fazer chamadas pesadas (ex: invocar o agente só para testar)
  - Vazar informações sensíveis de infraestrutura

Por que 200 vs 503?
--------------------
- 200 OK       → sistema pronto, pode receber tráfego
- 503 Service Unavailable → sistema não pronto (ex: agente não inicializou)

Orquestradores como Kubernetes usam isso para decidir se enviam tráfego
para este pod. Se o health check retorna 503, o pod é marcado como
"not ready" e o tráfego é redirecionado para outros pods.

Status dos componentes:
  - agent   → verifica se app.state.agent foi inicializado
  - langsmith → verifica se LANGCHAIN_API_KEY está configurada
               (não faz chamada de rede — só valida config local)
"""

import logging
import os
from typing import Literal

from fastapi import APIRouter, Request
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])

ComponentStatus = Literal["ok", "degraded", "unavailable"]


class ComponentHealth(BaseModel):
    """Status de um componente individual do sistema."""
    status: ComponentStatus
    detail: str | None = None


class HealthResponse(BaseModel):
    """Resposta do endpoint GET /health."""
    status: ComponentStatus
    version: str
    components: dict[str, ComponentHealth]


def _check_agent(request: Request) -> ComponentHealth:
    """Verifica se o agente Lupus está inicializado em app.state."""
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        return ComponentHealth(
            status="unavailable",
            detail="Agente não inicializado — aguarde o startup completar.",
        )
    return ComponentHealth(status="ok")


def _check_langsmith() -> ComponentHealth:
    """Verifica se as credenciais do LangSmith estão configuradas.

    Por que não fazemos uma chamada de rede aqui?
    ----------------------------------------------
    Um health check deve ser rápido e leve. Fazer uma chamada HTTP
    ao LangSmith durante o health check:
      1. Adiciona latência (~200ms) a cada verificação
      2. Pode causar falso negativo se o LangSmith estiver lento
      3. Não é necessário — se a key está presente, o SDK funciona

    Para quem precisa validar a conexão real, o /eval/run já faz isso.
    """
    api_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("LANGSMITH_API_KEY")
    tracing = os.environ.get("LANGCHAIN_TRACING_V2", "false").lower() == "true"

    if not api_key:
        return ComponentHealth(
            status="degraded",
            detail="LANGCHAIN_API_KEY não configurada — evals e tracing desabilitados.",
        )
    if not tracing:
        return ComponentHealth(
            status="degraded",
            detail="LANGCHAIN_TRACING_V2 não está ativo — tracing desabilitado.",
        )
    return ComponentHealth(status="ok")


@router.get(
    "",
    response_model=HealthResponse,
    summary="Status de saúde da API",
    description=(
        "Verifica se o servidor e seus componentes estão operacionais. "
        "Retorna 200 se tudo ok, 503 se algum componente crítico está indisponível."
    ),
)
async def health_check(request: Request) -> HealthResponse:
    """Verifica o status de todos os componentes e retorna um relatório.

    O status geral (top-level) segue a regra do componente mais crítico:
      - Se o agente está 'unavailable' → status geral = 'unavailable' → HTTP 503
      - Se algum componente está 'degraded' → status geral = 'degraded' → HTTP 200
      - Se tudo está 'ok' → status geral = 'ok' → HTTP 200

    Por que 'degraded' ainda retorna 200?
    ---------------------------------------
    LangSmith não configurado não impede o /chat de funcionar.
    O sistema está parcialmente operacional — não morto.
    503 seria enganoso para um load balancer: o servidor está sim
    disponível para receber tráfego de chat.
    """
    from fastapi import Response
    from fastapi.responses import JSONResponse

    components = {
        "agent": _check_agent(request),
        "langsmith": _check_langsmith(),
    }

    # Determina status geral
    statuses = [c.status for c in components.values()]
    if "unavailable" in statuses:
        overall = "unavailable"
    elif "degraded" in statuses:
        overall = "degraded"
    else:
        overall = "ok"

    response_body = HealthResponse(
        status=overall,
        version="0.1.0",
        components=components,
    )

    # HTTP 503 somente se componente crítico (agente) está indisponível
    http_status = 503 if overall == "unavailable" else 200
    return JSONResponse(
        content=response_body.model_dump(),
        status_code=http_status,
    )
