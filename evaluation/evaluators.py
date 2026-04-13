"""Evaluators para o LupusAPI — integração com LangSmith SDK.

O que é um evaluator no LangSmith?
------------------------------------
É uma função Python com uma assinatura específica:

    def my_evaluator(run: Run, example: Example) -> EvaluationResult:
        ...

Onde:
  - `run`     → o que o agente produziu (outputs, tempo, tools)
  - `example` → o que estava no dataset (inputs, expected outputs)

O LangSmith chama cada evaluator para cada exemplo do dataset,
coleta os scores, e salva tudo como um "experimento" histórico
que aparece no dashboard.

Temos 3 evaluators:
  1. keyword_correctness → verifica se keywords esperadas estão na resposta
  2. tool_usage          → verifica se as tools corretas foram chamadas
  3. latency             → penaliza respostas lentas

Por que 3 separados e não um único score?
-----------------------------------------
Cada métrica mede algo diferente:
  - um agente pode usar as tools certas mas dar uma resposta ruim
  - um agente pode ser rápido mas superficial
  
Separar permite identificar onde exatamente a qualidade cai.
"""

from __future__ import annotations

import logging

from langsmith.schemas import Example, Run

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Evaluator 1: Keyword Correctness
# ---------------------------------------------------------------------------

def keyword_correctness(run: Run, example: Example) -> dict:
    """Verifica se as keywords esperadas aparecem na resposta do agente.

    Score: proporção de keywords encontradas (0.0 a 1.0).
    Ex: 3 de 4 keywords encontradas → score = 0.75

    Por que keywords e não LLM-as-judge aqui?
    ------------------------------------------
    Keywords são determinísticas: rápidas, baratas, sem chamada extra ao LLM.
    Para fatos técnicos precisos (nome de tabelas, tecnologias, valores),
    presença de keyword é um sinal forte de correção.
    LLM-as-judge é melhor para qualidade subjetiva — usamos no Correctness.
    """
    response: str = (run.outputs or {}).get("response", "")
    expected_keywords: list = (example.outputs or {}).get("expected_keywords", [])

    if not expected_keywords:
        return {"key": "keyword_correctness", "score": 1.0}

    response_lower = response.lower()

    def _matches(kw_entry) -> bool:
        # Suporta string simples ou lista de sinônimos (ex: ["3", "três", "three"])
        if isinstance(kw_entry, list):
            return any(str(syn).lower() in response_lower for syn in kw_entry)
        return str(kw_entry).lower() in response_lower

    found = sum(1 for kw in expected_keywords if _matches(kw))
    score = found / len(expected_keywords)

    return {
        "key": "keyword_correctness",
        "score": score,
        "comment": f"{found}/{len(expected_keywords)} keywords encontradas",
    }


# ---------------------------------------------------------------------------
# Evaluator 2: Tool Usage
# ---------------------------------------------------------------------------

def tool_usage(run: Run, example: Example) -> dict:
    """Verifica se o agente chamou as tools esperadas para responder.

    Score: proporção de tools esperadas que foram realmente chamadas.
    Ex: esperava [analyze_code, search_codebase], chamou só [analyze_code] → 0.5

    Por que isso importa?
    ----------------------
    O agente pode "inventar" uma resposta sem usar tools (hallucination).
    Esta métrica detecta quando o agente respondeu sem consultar dados reais.

    Atenção: score 1.0 NÃO garante que a resposta está certa —
    só garante que o processo foi correto (usou as fontes esperadas).
    """
    tools_used: list[str] = (run.outputs or {}).get("tools_used", [])
    expected_tools: list[str] = (example.outputs or {}).get("expected_tools", [])

    if not expected_tools:
        return {"key": "tool_usage", "score": 1.0}

    tools_used_set = set(tools_used)
    expected_set = set(expected_tools)
    covered = expected_set & tools_used_set
    score = len(covered) / len(expected_set)

    missing = expected_set - tools_used_set
    comment = f"Cobertura: {covered or '∅'}"
    if missing:
        comment += f" | Faltaram: {missing}"

    return {"key": "tool_usage", "score": score, "comment": comment}


# ---------------------------------------------------------------------------
# Evaluator 3: Latency Score
# ---------------------------------------------------------------------------

# Limites de latência para o score (em milissegundos)
_LATENCY_EXCELLENT_MS = 10_000   # ≤ 10s → score 1.0
_LATENCY_ACCEPTABLE_MS = 60_000  # ≤ 60s → score entre 0.5 e 1.0
_LATENCY_MAX_MS = 180_000        # > 180s → score 0.0 (timeout)


def latency_score(run: Run, example: Example) -> dict:
    """Converte latência em score de 0.0 a 1.0.

    Escala:
        ≤ 10s  → 1.0  (excelente)
        ≤ 60s  → 0.5–1.0 (aceitável, degradação linear)
        > 60s  → 0.0–0.5 (lento, degradação linear até 180s)
        > 180s → 0.0  (timeout)

    Por que não só medir o tempo bruto?
    -------------------------------------
    Ter latência como score (0-1) permite agregá-la com os outros
    evaluators numa métrica composta, comparar entre runs diferentes,
    e definir um threshold de qualidade (ex: "score mínimo de 0.5").
    """
    latency_ms: float = (run.outputs or {}).get("latency_ms", 0.0)

    if latency_ms <= _LATENCY_EXCELLENT_MS:
        score = 1.0
    elif latency_ms <= _LATENCY_ACCEPTABLE_MS:
        # Interpolação linear: 10s → 1.0, 60s → 0.5
        score = 1.0 - 0.5 * (
            (latency_ms - _LATENCY_EXCELLENT_MS)
            / (_LATENCY_ACCEPTABLE_MS - _LATENCY_EXCELLENT_MS)
        )
    elif latency_ms <= _LATENCY_MAX_MS:
        # Interpolação linear: 60s → 0.5, 180s → 0.0
        score = 0.5 * (
            1.0 - (latency_ms - _LATENCY_ACCEPTABLE_MS)
            / (_LATENCY_MAX_MS - _LATENCY_ACCEPTABLE_MS)
        )
    else:
        score = 0.0

    return {
        "key": "latency_score",
        "score": round(score, 3),
        "comment": f"{latency_ms:.0f}ms",
    }


# Lista exportada — usada pelo eval_service
ALL_EVALUATORS = [keyword_correctness, tool_usage, latency_score]
