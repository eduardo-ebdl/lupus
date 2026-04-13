"""Middleware de logging estruturado para a LupusAPI.

O que é middleware no FastAPI?
-------------------------------
Um middleware é um "interceptador" que envolve TODAS as requisições:
cada request passa pelo middleware antes de chegar ao endpoint,
e cada response passa por ele antes de voltar ao cliente.

    Request → [Middleware] → Endpoint → [Middleware] → Response

Por que logging estruturado (JSON) ao invés de print()?
---------------------------------------------------------
`print()` produz texto livre — impossível de filtrar, agregar ou
enviar para sistemas como CloudWatch, Datadog ou Elastic.

Logging estruturado emite JSON com campos fixos:
    {"request_id": "abc", "method": "POST", "path": "/chat",
     "status": 200, "latency_ms": 1234, "timestamp": "..."}

Isso permite queries como:
    - "todas as requests > 5s nos últimos 10min"
    - "erros 500 agrupados por endpoint"
    - "distribuição de latência por rota"

O que logamos:
--------------
  - request_id  : UUID único por request (rastreabilidade)
  - method      : GET, POST, etc.
  - path        : /chat, /eval/run, etc.
  - status_code : 200, 422, 500, etc.
  - latency_ms  : tempo total de resposta em milissegundos
  - client_ip   : IP do cliente (para auditoria)

request_id é injetado como header na response também —
útil para correlacionar logs com erros reportados pelo cliente.
"""

import logging
import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger("lupusapi.access")


class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware que loga toda requisição com latência e request_id.

    Herda de BaseHTTPMiddleware — o padrão oficial do Starlette/FastAPI
    para middlewares que precisam interceptar request E response.

    Atenção: BaseHTTPMiddleware tem uma limitação: ele bufferiza o body
    da response para que o middleware possa lê-lo. Para streaming ou
    SSE (Server-Sent Events), usar outro approach. Para nossa API
    (responses JSON simples), é perfeito.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """Intercepta cada request: gera ID, mede latência, loga resultado.

        `call_next` é uma função async que você chama para continuar
        o processamento normal da requisição. Sem chamar call_next,
        a request nunca chega ao endpoint.

        Fluxo:
            1. Gera request_id único
            2. Registra início de tempo
            3. Chama o endpoint (call_next)
            4. Mede latência
            5. Adiciona X-Request-ID na response
            6. Loga tudo em JSON
        """
        request_id = str(uuid.uuid4())[:8]  # 8 chars → legível nos logs
        start = time.monotonic()

        # Injeta o request_id no estado da request para que endpoints
        # possam usá-lo se precisarem (ex: incluir no body de erro)
        request.state.request_id = request_id

        try:
            response: Response = await call_next(request)
        except Exception as exc:
            # Se o endpoint lançar uma exceção não tratada, ainda logamos
            latency_ms = round((time.monotonic() - start) * 1000, 2)
            logger.error(
                "request_id=%s method=%s path=%s status=500 latency_ms=%.2f error=%s",
                request_id, request.method, request.url.path, latency_ms, exc,
            )
            raise

        latency_ms = round((time.monotonic() - start) * 1000, 2)

        # Adiciona X-Request-ID no header da response — o cliente pode
        # usar isso para reportar problemas: "o ID da request com erro foi X"
        response.headers["X-Request-ID"] = request_id

        # Log estruturado — campos separados por espaço, fácil de parsear
        # com awk, grep, ou qualquer ferramenta de log
        log_fn = logger.warning if response.status_code >= 400 else logger.info
        log_fn(
            "request_id=%s method=%s path=%s status=%d latency_ms=%.2f ip=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            latency_ms,
            request.client.host if request.client else "unknown",
        )

        return response
