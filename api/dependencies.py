"""Dependências globais da LupusAPI.

O que é Dependency Injection (DI) no FastAPI?
----------------------------------------------
DI é um padrão onde o framework pergunta: "o que seu endpoint precisa?"
e entrega pronto, sem que o endpoint precise buscar sozinho.

Em vez de fazer isso dentro de cada endpoint:

    async def chat(body: ChatRequest):
        agent = app.state.agent          # ← endpoint sabe onde buscar
        result = await agent_service.invoke(agent, ...)

Você declara a dependência assim:

    async def chat(body: ChatRequest, agent=Depends(get_agent)):
        result = await agent_service.invoke(agent, ...)

Benefícios:
  1. Testabilidade: nos testes, você pode "injetar" um agente mock
     sem mudar nada no router:
         app.dependency_overrides[get_agent] = lambda: mock_agent

  2. Separação de responsabilidades: o endpoint não sabe de onde
     vem o agente, só como usá-lo.

  3. Gerenciamento automático de ciclo de vida: o FastAPI chama
     a função `get_agent()` em cada request e cuida do cleanup.

Como o agente chega aqui?
--------------------------
O agente é criado UMA VEZ no startup do servidor (em api/main.py, lifespan)
e armazenado em `app.state.agent`. Criar o agente é caro:
  - Carrega sentence-transformers
  - Conecta ao SQLite
  - Inicializa todos os middlewares do LangGraph

Por isso, criamos ele uma vez e reutilizamos a instância.
Sessões diferentes são separadas pelo `thread_id` — não por instâncias distintas.
"""

from fastapi import Depends, HTTPException, Request
from typing import Any


def get_agent(request: Request) -> Any:
    """Recupera a instância do agente Lupus do estado da aplicação.

    O `request: Request` é injetado automaticamente pelo FastAPI.
    Ele dá acesso a `request.app.state`, onde guardamos o agente.

    Raises:
        HTTPException 503: Se o agente não estiver inicializado.
                           Isso não deveria acontecer em operação normal,
                           mas é importante garantir uma mensagem clara
                           em vez de um AttributeError genérico.
    """
    agent = getattr(request.app.state, "agent", None)
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "O agente Lupus ainda não está inicializado. "
                "Aguarde o startup do servidor completar e tente novamente."
            ),
        )
    return agent
