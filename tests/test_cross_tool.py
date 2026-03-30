"""Teste cross-tool: perguntas que exigem 2+ tools para responder."""

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

CROSS_TOOL_QUESTIONS = [
    # Pergunta 1: Exige get_data_dictionary + map_data_lineage + analyze_dbt_model
    "Como a coluna nu_idade_n é transformada desde o dado bruto (Bronze) até o cálculo de faixa etária no Gold? "
    "Mostre o caminho completo: tipo no Bronze, transformação no Silver, e como é usada nos KPIs.",

    # Pergunta 2: Exige get_project_architecture + analyze_pipeline_config + analyze_dbt_model
    "Por que o modelo bronze_srag_data usa materialization ephemeral enquanto o silver usa table com liquid clustering? "
    "Como essa decisão se conecta com a arquitetura Medallion e o pipeline de deploy?",

    # Pergunta 3: Exige get_agent_tools_spec + get_data_dictionary + map_data_lineage
    "O AI Agent do SRAG usa a tool get_latest_srag_metrics para buscar dados. "
    "De quais colunas da Gold essa tool depende? E essas colunas, de onde vem na linhagem?",
]

# Agent criado uma vez — cada pergunta usa thread_id próprio (sem contaminação entre perguntas)
agent = make_agent()
results = []

for i, question in enumerate(CROSS_TOOL_QUESTIONS, 1):
    print(f"\n{'='*80}")
    print(f"PERGUNTA {i}")
    print(f"{'='*80}")
    print(f"{question}\n")
    print(f"{'-'*80}")
    print("RESPOSTA:")
    print(f"{'-'*80}\n")

    config = {"configurable": {"thread_id": str(uuid.uuid4())}}

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": question}]},
            config=config,
        )

        content = result["messages"][-1].content
        if isinstance(content, list):
            content = "\n".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        print(content)

        tool_calls = []
        for msg in result["messages"]:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append(tc.get("name", "unknown"))

        print(f"\n>>> Tools chamadas: {tool_calls}")
        print(f">>> Quantidade: {len(tool_calls)} tool calls")

        assert len(content) > 50, f"Pergunta {i}: resposta muito curta ({len(content)} chars)"
        assert len(tool_calls) >= 2, (
            f"Pergunta {i}: esperava 2+ tool calls (cross-tool), recebeu {len(tool_calls)}: {tool_calls}"
        )

        results.append({"id": i, "tools_called": tool_calls, "success": True})

    except AssertionError:
        raise
    except Exception as e:
        print(f"\nERRO: {e}")
        results.append({"id": i, "tools_called": [], "success": False, "error": str(e)})

# Resumo
print(f"\n{'='*80}")
print("RESUMO")
print(f"{'='*80}")
total = len(results)
success_count = sum(1 for r in results if r["success"])
print(f"Total: {total} | Sucesso: {success_count} | Falha: {total - success_count}")
for r in results:
    status = "OK" if r["success"] else "FALHA"
    tools = ", ".join(r["tools_called"]) if r["tools_called"] else "nenhuma"
    print(f"  [{status}] Pergunta {r['id']}: {tools}")

assert success_count == total, (
    f"\n{total - success_count}/{total} TESTES FALHARAM:\n" +
    "\n".join(
        f"  - Pergunta {r['id']}: {r.get('error', 'sem resposta ou tools insuficientes')}"
        for r in results if not r["success"]
    )
)
print(f"\nTodos os {total} testes passaram.")
