"""Schemas Pydantic para o endpoint POST /chat.

Por que Pydantic?
-----------------
O FastAPI usa Pydantic para validar e serializar dados automaticamente.
Quando você declara `body: ChatRequest` em um endpoint, o FastAPI:
  1. Lê o JSON da requisição
  2. Tenta construir um `ChatRequest` com esses dados
  3. Se falhar (campo errado, tipo errado), retorna HTTP 422 automaticamente
  4. Se passar, entrega o objeto Python já validado ao handler

Você não escreve nenhum código de validação manual — o tipo já é a documentação.
"""

from typing import Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    """Corpo da requisição para POST /chat."""

    message: str = Field(
        ...,  # "..." significa obrigatório em Pydantic
        min_length=1,
        max_length=10_000,
        description="Mensagem do usuário para o agente Lupus.",
        examples=["Qual a arquitetura deste repositório?"],
    )
    session_id: Optional[str] = Field(
        default=None,
        description=(
            "ID da sessão para manter histórico de conversa (multi-turn). "
            "Se não informado, o servidor cria uma sessão nova a cada requisição. "
            "Equivale ao `thread_id` do LangGraph."
        ),
        examples=["550e8400-e29b-41d4-a716-446655440000"],
    )


class ChatResponse(BaseModel):
    """Resposta do endpoint POST /chat."""

    response: str = Field(
        ...,
        description="Texto da resposta gerada pelo agente Lupus.",
    )
    session_id: str = Field(
        ...,
        description="ID da sessão usada. Guarde para continuar a conversa no próximo request.",
    )
    tools_used: list[str] = Field(
        default_factory=list,
        description="Nomes das tools que o agente chamou para responder.",
        examples=[["search_codebase", "analyze_code"]],
    )
    latency_ms: float = Field(
        ...,
        description="Tempo total de resposta do agente em milissegundos.",
    )
