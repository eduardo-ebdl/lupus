"""Teste de domain tools e sub-agents: 10 perguntas variadas.

Categorias:
- Domain tool simples (1 tool)
- Cross-tool (2+ domain tools)
- Sub-agent: analyze_code
- Sub-agent: generate_documentation
- Sub-agent: review_architecture
"""

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
    # --- Domain tool simples (1 tool) ---
    {
        "id": 1,
        "category": "domain_simple",
        "question": "Qual é o schedule do pipeline de ingestão de dados do SRAG?",
        "expected_tools": ["analyze_pipeline_config"],
    },
    {
        "id": 2,
        "category": "domain_simple",
        "question": "Liste todas as colunas da camada Silver com seus tipos.",
        "expected_tools": ["get_data_dictionary"],
    },
    # --- Cross-tool (2+ domain tools) ---
    {
        "id": 3,
        "category": "cross_tool",
        "question": "Como a coluna 'evolucao' do Bronze se transforma em 'obito_srag_flag' na Silver e depois em 'taxa_mortalidade_perc' na Gold?",
        "expected_tools": ["get_data_dictionary", "analyze_dbt_model", "map_data_lineage"],
    },
    {
        "id": 4,
        "category": "cross_tool",
        "question": "O AI Agent usa a tool generate_srag_charts. De qual tabela Gold ela puxa dados? Quais colunas são usadas no eixo X e Y?",
        "expected_tools": ["get_agent_tools_spec", "get_data_dictionary"],
    },
    # --- Sub-agent: analyze_code ---
    {
        "id": 5,
        "category": "subagent_code",
        "question": "Use a tool analyze_code para ler o arquivo 'srag_agent/models/silver/silver_srag_data.sql' e me explique como a lista de comorbidades é construída.",
        "expected_tools": ["analyze_code"],
    },
    {
        "id": 6,
        "category": "subagent_code",
        "question": "Use analyze_code para ler 'srag_agent/models/gold/gold_srag_daily.sql' e explique como o growth rate (taxa_aumento_casos_perc) é calculado.",
        "expected_tools": ["analyze_code"],
    },
    # --- Sub-agent: generate_documentation ---
    {
        "id": 7,
        "category": "subagent_doc",
        "question": "Use generate_documentation para gerar documentação sobre a arquitetura Medallion do projeto SRAG.",
        "expected_tools": ["generate_documentation"],
    },
    # --- Sub-agent: review_architecture ---
    {
        "id": 8,
        "category": "subagent_review",
        "question": "Use review_architecture para analisar: quais os trade-offs de usar Llama 3.3 70B hospedado no Databricks ao invés de uma API externa como OpenAI?",
        "expected_tools": ["review_architecture"],
    },
    # --- Misto: sub-agent + domain tool ---
    {
        "id": 9,
        "category": "mixed",
        "question": "Primeiro me diga quantas colunas tem a Gold Daily (use get_data_dictionary), depois use review_architecture para analisar se essa quantidade de KPIs é suficiente para monitoramento epidemiológico.",
        "expected_tools": ["get_data_dictionary", "review_architecture"],
    },
    {
        "id": 10,
        "category": "mixed",
        "question": "Qual a diferença entre as guardrails do AI Agent (use get_agent_tools_spec) e os dbt tests da Silver (use analyze_dbt_model)? Qual protege contra qual tipo de erro?",
        "expected_tools": ["get_agent_tools_spec", "analyze_dbt_model"],
    },
]

# Agent criado uma vez — cada pergunta usa thread_id próprio (sem contaminação entre perguntas)
agent = make_agent()
results = []

for q in QUESTIONS:
    print(f"\n{'='*80}")
    print(f"PERGUNTA {q['id']} [{q['category']}]")
    print(f"{'='*80}")
    print(f"{q['question']}\n")
    print(f"Tools esperadas: {q['expected_tools']}")
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
        print(f">>> Quantidade: {len(tool_calls)}")

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
print(f"Taxa de sucesso: {success_count}/{total} ({success_count*100//total}%)")
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
