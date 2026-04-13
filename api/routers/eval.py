"""Router do endpoint POST /eval/run.

O que este endpoint faz (Fase 3 — implementação real):
-------------------------------------------------------
1. Recebe quais evaluators rodar e qual dataset usar
2. Delega para eval_service.run() que:
   a. Garante que o dataset existe no LangSmith
   b. Define o agente Lupus como função-alvo
   c. Chama langsmith.evaluate() com os evaluators selecionados
   d. Coleta e retorna os resultados
3. Retorna um EvalResponse com scores por evaluator e URL do experimento

Este endpoint é um bom exemplo de como um endpoint FastAPI bem estruturado
NÃO contém lógica de negócio — só dela à lida com HTTP, delega ao serviço.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status

from api.dependencies import get_agent
from api.schemas.eval import EvalRequest, EvalResponse
import api.services.eval_service as eval_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/eval", tags=["Evaluation"])


@router.post(
    "/run",
    response_model=EvalResponse,
    summary="Executar avaliações LangSmith",
    description=(
        "Executa os evaluators selecionados sobre o dataset configurado no LangSmith. "
        "Retorna scores por evaluator e um link para o experimento no dashboard. "
        "⚠️ Esta operação é longa — pode levar vários minutos dependendo do número de exemplos."
    ),
)
async def run_eval(
    body: EvalRequest,
    agent=Depends(get_agent),
) -> EvalResponse:
    """Dispara as avaliações no LangSmith e retorna os resultados.

    Fluxo:
      1. Valida a request (feito pelo Pydantic automaticamente)
      2. Chama eval_service.run() passando os evaluators e o agente
      3. O serviço faz tudo: cria dataset, roda agent, puntua, publica
      4. Retorna o EvalResponse estruturado

    Erros possíveis:
      - 503: LangSmith não configurado (falta LANGCHAIN_API_KEY)
      - 400: Evaluators inválidos
      - 500: Erro inesperado na execução
    """
    try:
        result = await eval_service.run(request=body, agent=agent)
        return result

    except RuntimeError as e:
        # Erros de configuração (ex: falta de API key) → 503
        msg = str(e)
        if "langsmith" in msg.lower() or "api_key" in msg.lower() or "langchain" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"LangSmith indisponível: {msg}",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro ao executar avaliação: {msg}",
        )

    except ValueError as e:
        # Evaluators inválidos → 400
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    except Exception as e:
        logger.exception("Unexpected error in /eval/run: %s", e)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno inesperado: {str(e)[:200]}",
        )
