"""Schemas Pydantic para o endpoint GET /tools.

Por que expor as tools via API?
--------------------------------
Clientes da API (UIs, outros agentes, testes) precisam saber:
  - Quais ferramentas o agente tem disponível
  - O que cada uma faz

O GET /tools retorna isso de forma programática, sem que o cliente
precise ler o código-fonte. É o equivalente a uma "tabela de capabilities".
"""

from pydantic import BaseModel, Field


class ToolInfo(BaseModel):
    """Informações sobre uma tool individual do agente."""

    name: str = Field(..., description="Nome interno da tool (ex: 'search_codebase').")
    description: str = Field(
        ...,
        description="Descrição do que a tool faz, extraída do docstring.",
    )
    category: str = Field(
        ...,
        description="Categoria da tool (ex: 'discovery', 'domain', 'subagent', 'rag').",
    )


class ToolsResponse(BaseModel):
    """Resposta do endpoint GET /tools."""

    count: int = Field(..., description="Número total de tools disponíveis.")
    tools: list[ToolInfo] = Field(..., description="Lista de todas as tools.")
