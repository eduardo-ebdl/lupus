"""Router do endpoint POST /chat — Fase 2: Agente Lupus real.

O que mudou da Fase 1?
-----------------------
- O endpoint agora usa `Depends(get_agent)` para receber a instância do agente
- Chama `agent_service.invoke()` em vez de retornar mock
- Trata erros com os status HTTP corretos

Sobre códigos de status HTTP:
------------------------------
  400 Bad Request   → cliente enviou dados inválidos (já tratado pelo Pydantic → 422)
  422 Unprocessable → Pydantic não conseguiu validar o corpo (automático do FastAPI)
  503 Service Unavailable → agente não inicializado (tratado em dependencies.py)
  504 Gateway Timeout → agente demorou demais para responder
  500 Internal Server Error → erro inesperado no servidor

A regra de ouro: use o status code que melhor descreve QUEM errou.
  - 4xx → culpa do cliente
  - 5xx → culpa do servidor
"""

import uuid
from fastapi import APIRouter, Depends, HTTPException

from api.dependencies import get_agent
from api.schemas.chat import ChatRequest, ChatResponse
from api.services import agent_service

router = APIRouter(prefix="/chat", tags=["Chat"])


@router.post(
    "",
    response_model=ChatResponse,
    summary="Enviar mensagem ao agente Lupus",
    description=(
        "Envia uma mensagem para o agente Lupus e retorna a resposta. "
        "Use `session_id` para manter o histórico de conversa entre requisições.\n\n"
        "**Multi-turn**: guarde o `session_id` da resposta e reenvie nas próximas "
        "requisições para o agente lembrar o contexto da conversa."
    ),
    responses={
        504: {"description": "O agente não respondeu dentro do tempo limite (180s)."},
        503: {"description": "O agente não está disponível."},
        500: {"description": "Erro interno do servidor."},
    },
)
async def chat(
    body: ChatRequest,
    agent=Depends(get_agent),  # ← FastAPI injeta a instância do agente aqui
) -> ChatResponse:
    """Endpoint principal de conversa com o Lupus.

    O `agent` vem de `Depends(get_agent)`: o FastAPI chama `get_agent()`,
    que busca a instância em `app.state.agent` (criada no startup).
    O endpoint não sabe como o agente foi criado — só usa o que recebe.

    Isso é Dependency Injection na prática.
    """
    session = body.session_id or str(uuid.uuid4())

    try:
        response, tools_used, latency_ms = await agent_service.invoke(
            agent=agent,
            message=body.message,
            session_id=session,
        )
    except TimeoutError as e:
        # O agente demorou mais que 180s — problema do servidor, não do cliente
        raise HTTPException(status_code=504, detail=str(e))
    except RuntimeError as e:
        # Erro interno do agente (ex: LLM falhou, tool lançou exceção)
        raise HTTPException(status_code=500, detail=str(e))

    return ChatResponse(
        response=response,
        session_id=session,
        tools_used=tools_used,
        latency_ms=latency_ms,
    )
