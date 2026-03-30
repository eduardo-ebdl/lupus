"""Bloco 6: Avaliação quantitativa do agent com 20 perguntas.

Métricas:
- Accuracy (keywords encontradas na resposta)
- Tool coverage (tools esperadas foram chamadas)
- Completude + Relevância (LLM-as-judge via Gemini)
"""

import json
import os
import sys
import time
import uuid

# Path setup — must be before project imports
EVAL_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(EVAL_DIR, ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

DATASET_PATH = os.path.join(EVAL_DIR, "dataset.json")
RESULTS_PATH = os.path.join(EVAL_DIR, "results.json")

from langchain_google_genai import ChatGoogleGenerativeAI

from config import make_agent

# Load dataset
with open(DATASET_PATH, encoding="utf-8") as f:
    dataset = json.load(f)

# LLM-as-judge prompt
JUDGE_PROMPT = """Você é um avaliador técnico. Avalie a resposta do agent a uma pergunta sobre o projeto SRAG.

Pergunta: {question}
Keywords esperadas: {keywords}
Resposta do agent: {response}

Avalie de 1 a 5 em cada critério:
- **completude**: A resposta cobre todos os aspectos da pergunta? (1=muito incompleta, 5=completa)
- **relevância**: A resposta é relevante e precisa? (1=irrelevante, 5=muito relevante)
- **fundamentação**: A resposta parece baseada em dados reais do projeto? (1=inventada, 5=fundamentada)

Responda APENAS em JSON válido, sem markdown:
{{"completude": N, "relevancia": N, "fundamentacao": N}}"""


def _extract_content(result: dict) -> str:
    content = result["messages"][-1].content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return content if isinstance(content, str) else str(content)


def _extract_tool_calls(result: dict) -> list[str]:
    tool_calls = []
    for msg in result["messages"]:
        if hasattr(msg, "tool_calls") and msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(tc.get("name", "unknown"))
    return tool_calls


def _kw_match(response_lower: str, kw_entry) -> bool:
    """Check if a keyword entry matches. Supports str or list of synonyms."""
    if isinstance(kw_entry, list):
        return any(syn.lower() in response_lower for syn in kw_entry)
    return kw_entry.lower() in response_lower


def _kw_label(kw_entry) -> str:
    """Human-readable label for a keyword entry."""
    if isinstance(kw_entry, list):
        return kw_entry[0]
    return kw_entry


def _check_keywords(response: str, keywords: list) -> dict:
    response_lower = response.lower()
    found = [_kw_label(kw) for kw in keywords if _kw_match(response_lower, kw)]
    missing = [_kw_label(kw) for kw in keywords if not _kw_match(response_lower, kw)]
    return {
        "found": found,
        "missing": missing,
        "score": len(found) / len(keywords) if keywords else 0,
    }


def _check_tools(called: list[str], expected: list[str]) -> dict:
    called_set = set(called)
    expected_set = set(expected)
    covered = expected_set & called_set
    missing = expected_set - called_set
    return {
        "covered": list(covered),
        "missing": list(missing),
        "score": len(covered) / len(expected_set) if expected_set else 0,
    }


def _judge_response(question: str, keywords: list[str], response: str) -> dict:
    """Usa Gemini como juiz para avaliar completude, relevância e fundamentação."""
    judge_llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")
    kw_labels = [kw[0] if isinstance(kw, list) else kw for kw in keywords]
    prompt = JUDGE_PROMPT.format(
        question=question,
        keywords=", ".join(kw_labels),
        response=response[:2000],
    )
    try:
        result = judge_llm.invoke([{"role": "user", "content": prompt}])
        content = result.content.strip()
        # Remove markdown code block if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(content)
    except Exception as e:
        print(f"  [JUDGE ERROR] {e}")
        return {"completude": 0, "relevancia": 0, "fundamentacao": 0}


# Run evaluation
print(f"{'='*70}")
print(f"AVALIAÇÃO QUANTITATIVA — 25 PERGUNTAS")
print(f"{'='*70}")

# Agent criado uma vez — reutilizado entre perguntas para evitar cold start
# de middleware a cada pergunta. Thread ID separado por pergunta garante
# histórico isolado (sem contaminação de contexto entre perguntas).
agent = make_agent()

results = []

for q in dataset:
    print(f"\n[{q['id']}/{len(dataset)}] [{q['category']}] {q['question'][:60]}...")

    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
    start = time.time()

    MAX_RETRIES = 3
    RETRY_DELAYS = [5, 15, 30]

    try:
        result = None
        for attempt in range(MAX_RETRIES):
            try:
                result = agent.invoke(
                    {"messages": [{"role": "user", "content": q["question"]}]},
                    config=config,
                )
                break
            except Exception as retry_err:
                if attempt < MAX_RETRIES - 1:
                    delay = RETRY_DELAYS[attempt]
                    print(f"  [RETRY {attempt+1}/{MAX_RETRIES}] {retry_err} — aguardando {delay}s...")
                    time.sleep(delay)
                    # Fresh agent + thread for retry
                    agent = make_agent()
                    config = {"configurable": {"thread_id": str(uuid.uuid4())}}
                else:
                    raise
        elapsed = time.time() - start
        response = _extract_content(result)
        tool_calls = _extract_tool_calls(result)

        # Keyword check
        kw_result = _check_keywords(response, q["expected_keywords"])

        # Tool coverage check
        tool_result = _check_tools(tool_calls, q["expected_tools"])

        # LLM-as-judge
        judge = _judge_response(q["question"], q["expected_keywords"], response)

        print(f"  Keywords: {kw_result['score']:.0%} | Tools: {tool_result['score']:.0%} | "
              f"Judge: C={judge.get('completude',0)} R={judge.get('relevancia',0)} F={judge.get('fundamentacao',0)} | "
              f"{elapsed:.1f}s")

        results.append({
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "response_length": len(response),
            "response_preview": response[:300],
            "tools_called": tool_calls,
            "keyword_accuracy": kw_result,
            "tool_coverage": tool_result,
            "judge_scores": judge,
            "time_seconds": round(elapsed, 1),
            "success": True,
        })

    except Exception as e:
        elapsed = time.time() - start
        print(f"  ERRO: {e} ({elapsed:.1f}s)")
        results.append({
            "id": q["id"],
            "category": q["category"],
            "question": q["question"],
            "response_length": 0,
            "tools_called": [],
            "keyword_accuracy": {"found": [], "missing": q["expected_keywords"], "score": 0},
            "tool_coverage": {"covered": [], "missing": q["expected_tools"], "score": 0},
            "judge_scores": {"completude": 0, "relevancia": 0, "fundamentacao": 0},
            "time_seconds": round(elapsed, 1),
            "success": False,
            "error": str(e),
        })

# Calculate metrics
total = len(results)
success_count = sum(1 for r in results if r["success"])

avg_keyword_accuracy = sum(r["keyword_accuracy"]["score"] for r in results) / total
avg_tool_coverage = sum(r["tool_coverage"]["score"] for r in results) / total
avg_completude = sum(r["judge_scores"].get("completude", 0) for r in results) / total
avg_relevancia = sum(r["judge_scores"].get("relevancia", 0) for r in results) / total
avg_fundamentacao = sum(r["judge_scores"].get("fundamentacao", 0) for r in results) / total
total_time = sum(r["time_seconds"] for r in results)

# Per category
categories = ["arquitetura", "modulos", "integracao", "design", "rag"]
category_metrics = {}
for cat in categories:
    cat_results = [r for r in results if r["category"] == cat]
    if cat_results:
        category_metrics[cat] = {
            "count": len(cat_results),
            "keyword_accuracy": sum(r["keyword_accuracy"]["score"] for r in cat_results) / len(cat_results),
            "tool_coverage": sum(r["tool_coverage"]["score"] for r in cat_results) / len(cat_results),
            "avg_completude": sum(r["judge_scores"].get("completude", 0) for r in cat_results) / len(cat_results),
            "avg_relevancia": sum(r["judge_scores"].get("relevancia", 0) for r in cat_results) / len(cat_results),
            "avg_fundamentacao": sum(r["judge_scores"].get("fundamentacao", 0) for r in cat_results) / len(cat_results),
        }

# Overall accuracy (keyword >= 0.5 AND judge completude >= 3)
accurate_count = sum(
    1 for r in results
    if r["keyword_accuracy"]["score"] >= 0.5
    and r["judge_scores"].get("completude", 0) >= 3
)
overall_accuracy = accurate_count / total

# Save results
output = {
    "metadata": {
        "date": "2026-03-24",
        "total_questions": total,
        "total_success": success_count,
        "total_time_seconds": round(total_time, 1),
    },
    "overall_metrics": {
        "accuracy": round(overall_accuracy, 4),
        "keyword_accuracy_avg": round(avg_keyword_accuracy, 4),
        "tool_coverage_avg": round(avg_tool_coverage, 4),
        "completude_avg": round(avg_completude, 2),
        "relevancia_avg": round(avg_relevancia, 2),
        "fundamentacao_avg": round(avg_fundamentacao, 2),
    },
    "category_metrics": category_metrics,
    "results": results,
}

with open(RESULTS_PATH, "w", encoding="utf-8") as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

# Print summary
print(f"\n{'='*70}")
print("RESUMO DA AVALIAÇÃO")
print(f"{'='*70}")
print(f"Total: {total} | Sucesso: {success_count} | Falha: {total - success_count}")
print(f"Tempo total: {total_time:.0f}s ({total_time/60:.1f}min)")
print()
print(f"ACCURACY GERAL: {overall_accuracy:.0%} (target: >= 75%)")
print(f"  Keyword accuracy média: {avg_keyword_accuracy:.0%}")
print(f"  Tool coverage média: {avg_tool_coverage:.0%}")
print(f"  Completude média (1-5): {avg_completude:.1f}")
print(f"  Relevância média (1-5): {avg_relevancia:.1f}")
print(f"  Fundamentação média (1-5): {avg_fundamentacao:.1f}")
print()
print("POR CATEGORIA:")
for cat, m in category_metrics.items():
    print(f"  {cat}: kw={m['keyword_accuracy']:.0%} tools={m['tool_coverage']:.0%} "
          f"C={m['avg_completude']:.1f} R={m['avg_relevancia']:.1f} F={m['avg_fundamentacao']:.1f}")

print(f"\nResultados salvos em: {RESULTS_PATH}")
