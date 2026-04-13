"""Schemas Pydantic para o endpoint POST /eval/run.

O modelo mental de evals no LangSmith:
---------------------------------------
  Dataset  →  Evaluator(s)  →  Experiment Results
  
  - Dataset: conjunto de inputs + outputs esperados (nosso .jsonl)
  - Evaluator: função que recebe (input, output, expected) e retorna uma pontuação
  - Experiment: uma "rodada" de avaliação — LangSmith guarda os resultados históricos

Neste endpoint, o cliente informa:
  - Quais evaluators rodar (ou "all")
  - (Opcional) Qual dataset usar
  - (Opcional) Um subset de exemplos para teste rápido
"""

from typing import Literal, Optional
from pydantic import BaseModel, Field


# Tipo literal dos evaluators disponíveis — garante que só valores válidos são aceitos
EvaluatorName = Literal["correctness", "tool_usage", "latency", "all"]


class EvalRequest(BaseModel):
    """Corpo da requisição para POST /eval/run."""

    evaluators: list[EvaluatorName] = Field(
        default=["all"],
        description=(
            "Lista de evaluators para executar. "
            "Use ['all'] para rodar todos. "
            "Opções: 'correctness', 'tool_usage', 'latency'."
        ),
        examples=[["correctness", "latency"]],
    )
    dataset_name: Optional[str] = Field(
        default="lupus-chat-qa",
        description="Nome do dataset no LangSmith. Padrão: 'lupus-chat-qa'.",
    )
    max_examples: Optional[int] = Field(
        default=None,
        ge=1,
        le=100,
        description="Limita o número de exemplos do dataset. Útil para testes rápidos.",
        examples=[5],
    )


class EvalResultItem(BaseModel):
    """Resultado de um único exemplo avaliado."""

    input: str = Field(..., description="Pergunta/input avaliado.")
    evaluator: str = Field(..., description="Nome do evaluator que gerou este resultado.")
    score: float = Field(..., ge=0.0, le=1.0, description="Pontuação entre 0.0 e 1.0.")
    reasoning: Optional[str] = Field(
        default=None,
        description="Justificativa gerada pelo LLM-as-judge (apenas para 'correctness').",
    )


class EvalResponse(BaseModel):
    """Resposta do endpoint POST /eval/run."""

    experiment_name: str = Field(
        ...,
        description="Nome do experimento criado no LangSmith.",
    )
    experiment_url: Optional[str] = Field(
        default=None,
        description="URL para ver resultados no dashboard do LangSmith.",
    )
    summary: dict[str, float] = Field(
        ...,
        description="Média de cada evaluator. Ex: {'correctness': 0.85, 'latency': 0.92}",
    )
    results: list[EvalResultItem] = Field(
        ...,
        description="Resultado por exemplo avaliado.",
    )
