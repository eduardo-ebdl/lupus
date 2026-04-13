"""Router do endpoint GET /tools.

Este é o único endpoint que já está 100% real desde a Fase 1.
Por quê? Porque ele só precisa ler metadados das tools — não precisa
invocar o agente, não precisa de async pesado, não precisa de LangSmith.

Como extraímos os metadados das tools?
---------------------------------------
As tools do Lupus são funções Python decoradas com `@tool` do LangChain.
Essa decoração adiciona atributos à função:
  - `tool.name` → nome da tool
  - `tool.description` → docstring formatada

Nós também mapeamos cada tool à sua categoria (DISCOVERY, DOMAIN, etc.)
usando os grupos definidos em `tools/__init__.py`.
"""

from fastapi import APIRouter

from api.schemas.tools import ToolInfo, ToolsResponse

# Importamos os grupos de tools para saber a categoria de cada uma
from tools import (
    ALL_TOOLS,
    DISCOVERY_TOOLS,
    DOMAIN_TOOLS,
    SUBAGENT_TOOLS,
    RAG_TOOLS,
)

router = APIRouter(prefix="/tools", tags=["Tools"])

# Mapa reverso: tool_name → categoria
# Construído uma vez no import, não a cada requisição (eficiência)
_TOOL_CATEGORY: dict[str, str] = {}
for t in DISCOVERY_TOOLS:
    _TOOL_CATEGORY[t.name] = "discovery"
for t in DOMAIN_TOOLS:
    _TOOL_CATEGORY[t.name] = "domain"
for t in SUBAGENT_TOOLS:
    _TOOL_CATEGORY[t.name] = "subagent"
for t in RAG_TOOLS:
    _TOOL_CATEGORY[t.name] = "rag"


@router.get(
    "",
    response_model=ToolsResponse,
    summary="Listar todas as tools do agente",
    description=(
        "Retorna a lista completa de ferramentas disponíveis para o agente Lupus, "
        "incluindo nome, descrição e categoria de cada uma."
    ),
)
async def list_tools() -> ToolsResponse:
    """Retorna metadados de todas as 17 tools do agente Lupus."""
    tool_infos = [
        ToolInfo(
            name=tool.name,
            # Pega só a primeira linha do docstring para não poluir a resposta
            description=(tool.description or "Sem descrição.").split("\n")[0].strip(),
            category=_TOOL_CATEGORY.get(tool.name, "unknown"),
        )
        for tool in ALL_TOOLS
    ]

    return ToolsResponse(count=len(tool_infos), tools=tool_infos)
