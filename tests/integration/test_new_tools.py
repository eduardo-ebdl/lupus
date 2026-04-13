"""Testes para as novas tools: discover_project (expandido), explore_repository,
read_data_file e suggest_improvements.

Roda contra o srag_agent/ como repositório de teste padrão.
"""

import json
import os
import sys
import uuid

# Path setup — must be before project imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv()

from config import make_agent

QUESTIONS = [
    # --- discover_project: detecção de tecnologias ---
    {
        "id": 1,
        "category": "discover_project",
        "question": "Quais tecnologias esse projeto usa? Me dá uma visão geral do stack.",
        "expected_tools": ["discover_project"],
        "check": "deve detectar dbt e/ou databricks no srag_agent",
    },
    # --- explore_repository: estrutura de arquivos ---
    {
        "id": 2,
        "category": "explore_repository",
        "question": "Me mostra a estrutura completa de arquivos e diretórios do projeto.",
        "expected_tools": ["explore_repository"],
        "check": "deve listar diretórios e arquivos com tipos identificados",
    },
    # --- suggest_improvements: análise crítica ---
    {
        "id": 3,
        "category": "suggest_improvements",
        "question": "Analisa o projeto e me dá sugestões de melhoria técnica.",
        "expected_tools": ["suggest_improvements"],
        "check": "deve retornar sugestões categorizadas com evidências do repo",
    },
    # --- suggest_improvements com foco ---
    {
        "id": 4,
        "category": "suggest_improvements_focused",
        "question": "Quais melhorias você sugere para a área de testes desse projeto?",
        "expected_tools": ["suggest_improvements"],
        "check": "deve focar em cobertura de testes e qualidade",
    },
    # --- read_data_file: erro esperado (sem CSV no srag_agent) ---
    {
        "id": 5,
        "category": "read_data_file_error",
        "question": "Existe algum arquivo de dados (CSV, JSON) no projeto que eu possa analisar? Se sim, mostre a estrutura.",
        "expected_tools": ["discover_project", "explore_repository"],
        "check": "deve verificar se há dados locais antes de tentar ler",
    },
    # --- discover_project + explore: cross-tool ---
    {
        "id": 6,
        "category": "cross_discovery",
        "question": "Quais arquivos de configuração existem no projeto e o que cada um configura?",
        "expected_tools": ["discover_project", "explore_repository"],
        "check": "deve identificar arquivos-chave e explicar seu propósito",
    },
]

agent = make_agent()
results = []

for q in QUESTIONS:
    print(f"\n{'='*80}")
    print(f"PERGUNTA {q['id']} [{q['category']}]")
    print(f"{'='*80}")
    print(f"{q['question']}\n")
    print(f"Tools esperadas: {q['expected_tools']}")
    print(f"Check: {q['check']}")
    print(f"{'-'*80}")

    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": q["question"]}]},
            config=config,
        )

        content = result["messages"][-1].content
        if isinstance(content, list):
            content = "\n".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )

        tool_calls = []
        for msg in result["messages"]:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append(tc.get("name", "unknown"))

        print(f"\nRESPOSTA (primeiros 500 chars):")
        print(content[:500] if content else "(vazio)")
        print(f"\n>>> Tools chamadas: {tool_calls}")

        assert len(content) > 50, f"Pergunta {q['id']}: resposta muito curta ({len(content)} chars)"
        assert len(tool_calls) > 0, f"Pergunta {q['id']}: nenhuma tool foi chamada"

        results.append({
            "id": q["id"],
            "category": q["category"],
            "tools_called": tool_calls,
            "success": True,
            "response_length": len(content),
        })

    except AssertionError:
        raise
    except Exception as e:
        print(f"\nERRO: {e}")
        results.append({
            "id": q["id"],
            "category": q["category"],
            "tools_called": [],
            "success": False,
            "error": str(e),
        })

# Resumo
print(f"\n{'='*80}")
print("RESUMO")
print(f"{'='*80}")
total = len(results)
success_count = sum(1 for r in results if r["success"])
print(f"Total: {total} | Sucesso: {success_count} | Falha: {total - success_count}")
print()
for r in results:
    status = "OK" if r["success"] else "FALHA"
    tools = ", ".join(r["tools_called"]) if r["tools_called"] else "nenhuma"
    print(f"  [{status}] Pergunta {r['id']} ({r['category']}): {tools}")

assert success_count == total, (
    f"\n{total - success_count}/{total} TESTES FALHARAM:\n" +
    "\n".join(
        f"  - Pergunta {r['id']} ({r['category']}): {r.get('error', 'sem resposta ou tools')}"
        for r in results if not r["success"]
    )
)
print(f"\nTodos os {total} testes passaram.")
