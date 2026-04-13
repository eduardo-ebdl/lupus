"""Serviço de avaliação — integração com LangSmith SDK.

O que este módulo faz:
----------------------
Orquestra uma "rodada de avaliação" completa no LangSmith:

  1. Carrega (ou cria) o dataset remoto no LangSmith
  2. Define a função-alvo: (inputs) → outputs  (é o agente Lupus)
  3. Chama langsmith.evaluate() com os evaluators escolhidos
  4. Coleta os resultados e os transforma no formato da API

O modelo mental de evals no LangSmith
--------------------------------------
  Dataset  →  Target Function  →  Evaluators  →  Experiment

  - Dataset: conjunto de exemplos (pergunta + expected)
  - Target Function: o que você quer avaliar (nosso agente)
  - Evaluator: função que puntua (input, output, expected) → score
  - Experiment: uma rodada histórica, visível no dashboard

Por que usar langsmith.evaluate() e não rodar direto?
-----------------------------------------------------
A API `evaluate()` do SDK faz mais do que chamar sua função:
  - Cria o "experiment" no LangSmith com metadata
  - Armazena cada run individualmente (com traces!)
  - Chama os evaluators para cada run automaticamente
  - Calcula médias e publica tudo no dashboard
  
Fazendo na mão, você perderia o histórico e o dashboard.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import langsmith
from langsmith import Client as LangSmithClient

from api.schemas.eval import EvalRequest, EvalResponse, EvalResultItem
from evaluation.evaluators import ALL_EVALUATORS, keyword_correctness, latency_score, tool_usage

logger = logging.getLogger(__name__)

# Caminho para o dataset local (.jsonl) — usado para popular o LangSmith
_DATASET_JSONL = Path(__file__).parents[2] / "evaluation" / "datasets" / "chat_qa.jsonl"

# Mapeamento nome → função evaluator
_EVALUATOR_MAP = {
    "correctness": keyword_correctness,
    "tool_usage": tool_usage,
    "latency_score": latency_score,
}


# ---------------------------------------------------------------------------
# Dataset: upload local → LangSmith
# ---------------------------------------------------------------------------

def _ensure_langsmith_dataset(client: LangSmithClient, dataset_name: str) -> str:
    """Garante que o dataset existe no LangSmith e retorna seu ID.

    Estratégia:
      - Se já existe dataset com esse nome → reutiliza (não duplica)
      - Se não existe → cria a partir do .jsonl local

    Por que reutilizar ao invés de sempre recriar?
    -----------------------------------------------
    O LangSmith rastreia histórico por dataset. Se você recria o dataset
    a cada eval, perde a rastreabilidade de qual versão dos dados gerou
    qual resultado. Reutilizar o mesmo dataset permite comparar runs
    ao longo do tempo (ex: "o agent melhorou nessa semana?").
    """
    # Verifica se já existe
    datasets = list(client.list_datasets(dataset_name=dataset_name))
    if datasets:
        dataset_id = str(datasets[0].id)
        logger.info("LangSmith dataset '%s' já existe (id=%s)", dataset_name, dataset_id)
        return dataset_id

    # Cria e popula a partir do .jsonl local
    logger.info("Criando dataset '%s' no LangSmith...", dataset_name)
    dataset = client.create_dataset(
        dataset_name=dataset_name,
        description=(
            "Dataset de avaliação do Lupus Agent — 20 perguntas sobre o projeto SRAG "
            "com keywords e tools esperadas."
        ),
    )

    # Lê exemplos do .jsonl
    examples: list[dict] = []
    with open(_DATASET_JSONL, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                examples.append(json.loads(line))

    # Cria exemplos no LangSmith (em batch)
    client.create_examples(
        inputs=[ex["inputs"] for ex in examples],
        outputs=[ex["outputs"] for ex in examples],
        dataset_id=dataset.id,
    )

    logger.info(
        "Dataset '%s' criado com %d exemplos (id=%s)",
        dataset_name, len(examples), dataset.id,
    )
    return str(dataset.id)


# ---------------------------------------------------------------------------
# Target Function: agente Lupus como callable para o LangSmith
# ---------------------------------------------------------------------------

def _make_target_fn(agent: Any) -> callable:
    """Cria a função-alvo que o LangSmith irá avaliar.

    O LangSmith chama target_fn(inputs) para cada exemplo do dataset.
    A função deve retornar um dict com os outputs que os evaluators irão ler.

    Por que retornar 'response', 'tools_used' e 'latency_ms' separados?
    --------------------------------------------------------------------
    Cada evaluator lê uma chave diferente do output:
      - keyword_correctness lê 'response'
      - tool_usage lê 'tools_used'
      - latency_score lê 'latency_ms'

    Se você retornasse só 'response', os outros dois evaluators ficariam cegos.
    """
    import time

    def target_fn(inputs: dict) -> dict:
        """Invoca o agente Lupus de forma síncrona (LangSmith é sync)."""
        question = inputs.get("question", "")
        session_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": session_id}}
        input_payload = {"messages": [{"role": "user", "content": question}]}

        start = time.monotonic()
        try:
            result = agent.invoke(input_payload, config)
        except Exception as e:
            logger.error("Agent invoke error during eval: %s", e)
            return {"response": "", "tools_used": [], "latency_ms": 0.0}

        latency_ms = round((time.monotonic() - start) * 1000, 2)

        # Extrai resposta e tools usadas
        messages = result.get("messages", [])
        response_text = ""
        for msg in reversed(messages):
            if getattr(msg, "type", "") != "ai":
                continue
            content = getattr(msg, "content", "")
            if isinstance(content, list):
                content = "\n".join(
                    block.get("text", "") for block in content
                    if isinstance(block, dict)
                )
            if isinstance(content, str) and content.strip():
                response_text = content
                break

        tools_used: list[str] = []
        seen: set[str] = set()
        for msg in messages:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                    if name and name not in seen:
                        tools_used.append(name)
                        seen.add(name)

        return {
            "response": response_text,
            "tools_used": tools_used,
            "latency_ms": latency_ms,
        }

    return target_fn


# ---------------------------------------------------------------------------
# Função principal do serviço
# ---------------------------------------------------------------------------

async def run(request: EvalRequest, agent: Any) -> EvalResponse:
    """Executa a avaliação e retorna os resultados.

    Fluxo completo:
      1. Inicializa o client LangSmith (usa LANGCHAIN_API_KEY do env)
      2. Garante que o dataset existe no LangSmith
      3. Seleciona os evaluators pedidos pelo cliente
      4. Executa langsmith.evaluate() em thread separada (é bloqueante)
      5. Coleta resultados e monta EvalResponse

    Args:
        request: Corpo da requisição com evaluators, dataset_name, max_examples.
        agent: Instância do agente Lupus (criado por make_agent()).

    Returns:
        EvalResponse com experiment_name, experiment_url, summary e results.
    """
    # 1. Inicializa client
    api_key = os.environ.get("LANGCHAIN_API_KEY") or os.environ.get("LANGSMITH_API_KEY")
    if not api_key:
        raise RuntimeError(
            "LangSmith não configurado. "
            "Defina LANGCHAIN_API_KEY ou LANGSMITH_API_KEY no .env"
        )
    client = LangSmithClient(api_key=api_key)

    # 2. Garante dataset remoto
    dataset_name = request.dataset_name or "lupus-chat-qa"
    dataset_id = await asyncio.to_thread(_ensure_langsmith_dataset, client, dataset_name)

    # 3. Seleciona evaluators
    if "all" in request.evaluators:
        selected_evaluators = list(_EVALUATOR_MAP.values())
        selected_names = list(_EVALUATOR_MAP.keys())
    else:
        selected_evaluators = [
            _EVALUATOR_MAP[name]
            for name in request.evaluators
            if name in _EVALUATOR_MAP
        ]
        selected_names = [n for n in request.evaluators if n in _EVALUATOR_MAP]

    if not selected_evaluators:
        raise ValueError(
            f"Nenhum evaluator válido. Disponíveis: {list(_EVALUATOR_MAP.keys())}"
        )

    # 4. Monta nome único do experimento
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    experiment_name = f"lupus-eval-{timestamp}"
    target_fn = _make_target_fn(agent)

    logger.info(
        "Iniciando experimento '%s' com %d evaluators sobre dataset '%s'",
        experiment_name, len(selected_evaluators), dataset_name,
    )

    # 5. Executa avaliação (langsmith.evaluate é bloqueante → thread)
    def _run_evaluate():
        return langsmith.evaluate(
            target_fn,
            data=dataset_name,
            evaluators=selected_evaluators,
            experiment_prefix=experiment_name,
            max_concurrency=1,  # Agente não é thread-safe; serial é seguro
            num_repetitions=1,
            # limit: restringe exemplos se max_examples foi passado
            **({"limit": request.max_examples} if request.max_examples else {}),
        )

    eval_results = await asyncio.to_thread(_run_evaluate)

    # 6. Coleta resultados por evaluator
    result_items: list[EvalResultItem] = []
    scores_per_evaluator: dict[str, list[float]] = {name: [] for name in selected_names}

    for r in eval_results:
        # Cada `r` é um EvaluationResult com .run, .example, .evaluation_results
        input_question = (r.example.inputs or {}).get("question", "")
        for ev_name in selected_names:
            # O resultado de cada evaluator fica em evaluation_results[ev_name]
            ev_result = (r.evaluation_results or {}).get(ev_name, {})
            score = float(ev_result.get("score", 0.0)) if ev_result else 0.0
            comment = ev_result.get("comment") if ev_result else None

            result_items.append(
                EvalResultItem(
                    input=input_question,
                    evaluator=ev_name,
                    score=score,
                    reasoning=comment,
                )
            )
            scores_per_evaluator[ev_name].append(score)

    # 7. Calcula médias por evaluator
    summary = {
        name: round(sum(scores) / len(scores), 4) if scores else 0.0
        for name, scores in scores_per_evaluator.items()
    }

    # 8. Tenta obter URL do experimento no LangSmith
    experiment_url: str | None = None
    try:
        experiments = list(client.list_projects(name=experiment_name, limit=1))
        if experiments:
            base_url = os.environ.get("LANGCHAIN_ENDPOINT", "https://smith.langchain.com")
            project_id = str(experiments[0].id)
            experiment_url = f"{base_url}/projects/{project_id}"
    except Exception:
        pass  # URL é opcional — não deve travar a resposta

    logger.info(
        "Avaliação concluída. Experimento: %s | Summary: %s",
        experiment_name, summary,
    )

    return EvalResponse(
        experiment_name=experiment_name,
        experiment_url=experiment_url,
        summary=summary,
        results=result_items,
    )
