"""Serviço de invocação do agente Lupus para uso via HTTP.

O problema central desta fase — e por que importa entender:
------------------------------------------------------------
O FastAPI é assíncrono: ele roda num event loop (asyncio).
O event loop é como um cozinheiro num restaurante: ele só tem duas mãos,
mas consegue atender vários pedidos simultâneos PORQUE enquanto espera o
forno assar um prato, ele trabalha em outro.

O problema é que `agent.invoke()` é SÍNCRONO e BLOQUEANTE.
É como se o cozinheiro travasse na frente do forno sem fazer mais nada.

Se fizermos isso diretamente dentro de um `async def`:

    async def chat_endpoint(body):
        result = agent.invoke(...)  # ← BLOQUEIA O EVENT LOOP INTEIRO
        return result

...o servidor inteiro para enquanto o agente pensa.
Nenhuma outra requisição é atendida nesse tempo.

A solução: `asyncio.to_thread()`
---------------------------------
Esta função pega uma chamada síncrona e a executa numa thread separada
(do thread pool interno do Python), liberando o event loop para continuar.

    result = await asyncio.to_thread(agent.invoke, args...)

Agora o event loop delega o trabalho pesado para uma thread e continua
servindo outras requisições. Quando a thread termina, o resultado volta.

Isso é o padrão correto para integrar código sync com frameworks async.
`asyncio.to_thread` está disponível desde Python 3.9.
"""

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def _extract_response_and_tools(result: dict) -> tuple[str, list[str]]:
    """Extrai texto da resposta e lista de tools usadas do resultado do agente.

    O LangGraph retorna um dict com a chave 'messages', uma lista de objetos
    de mensagem. Precisamos:
      1. Achar a última mensagem AI com conteúdo não-vazio → resposta
      2. Achar todas as mensagens com tool_calls → tools usadas

    Isso é separado em função pura para facilitar testes unitários sem
    precisar subir o agente inteiro.
    """
    messages = result.get("messages", [])

    # Extrai as tools chamadas (sem duplicatas, preservando ordem)
    tools_used: list[str] = []
    seen: set[str] = set()
    for msg in messages:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                name = (
                    tc.get("name", "") if isinstance(tc, dict)
                    else getattr(tc, "name", "")
                )
                if name and name not in seen:
                    tools_used.append(name)
                    seen.add(name)

    # Extrai o texto da última mensagem AI não-vazia
    response_text = ""
    for msg in reversed(messages):
        if getattr(msg, "type", "") != "ai":
            continue
        content = getattr(msg, "content", "")
        # Conteúdo pode ser string ou lista de blocos (formato Anthropic/Google)
        if isinstance(content, list):
            content = "\n".join(
                block.get("text", "") for block in content
                if isinstance(block, dict)
            )
        if isinstance(content, str) and content.strip():
            response_text = content
            break

    return response_text, tools_used


async def invoke(
    agent: Any,
    message: str,
    session_id: str,
    timeout_seconds: int = 180,
) -> tuple[str, list[str], float]:
    """Invoca o agente Lupus de forma assíncrona e segura.

    Usa `asyncio.to_thread` para não bloquear o event loop do FastAPI.

    Args:
        agent: Instância do agente LangGraph (criado por make_agent()).
        message: Mensagem do usuário.
        session_id: ID da sessão — mapeia ao thread_id do LangGraph,
                    permitindo histórico multi-turn.
        timeout_seconds: Timeout máximo. Padrão: 180s (igual ao CLI).

    Returns:
        Tupla (response_text, tools_used, latency_ms)

    Raises:
        TimeoutError: Se o agente não responder dentro do timeout.
        RuntimeError: Para outros erros de execução do agente.
    """
    config = {"configurable": {"thread_id": session_id}}
    input_payload = {"messages": [{"role": "user", "content": message}]}

    start = time.monotonic()

    try:
        # asyncio.to_thread executa agent.invoke() numa thread do pool,
        # liberando o event loop para atender outras requisições enquanto espera.
        result = await asyncio.wait_for(
            asyncio.to_thread(agent.invoke, input_payload, config),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError:
        elapsed = round((time.monotonic() - start) * 1000, 2)
        logger.warning("Agent timeout after %.0fs for session %s", timeout_seconds, session_id)
        raise TimeoutError(
            f"O agente não respondeu em {timeout_seconds}s. "
            "Tente uma pergunta mais simples ou verifique o repositório configurado."
        )
    except Exception as e:
        logger.exception("Agent invoke error for session %s: %s", session_id, e)
        raise RuntimeError(f"Erro interno do agente: {str(e)[:200]}") from e

    latency_ms = round((time.monotonic() - start) * 1000, 2)
    response_text, tools_used = _extract_response_and_tools(result)

    if not response_text:
        response_text = "O agente não gerou uma resposta. Tente reformular sua pergunta."

    logger.info(
        "session=%s tools=%s latency=%.0fms",
        session_id, tools_used, latency_ms,
    )

    return response_text, tools_used, latency_ms
