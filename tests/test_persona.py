"""Teste da persona Lupus.

Testa tom, limites, uso de tools e consistência.
Roda as 7 perguntas em sequência no mesmo thread (conversa multi-turn).
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
    {
        "id": 1,
        "category": "saudacao",
        "question": "Oi!",
        "checks": ["identificação como Lupus", "sem explicação técnica não solicitada"],
    },
    {
        "id": 2,
        "category": "tecnica_direta",
        "question": "O que é a arquitetura Medallion do projeto?",
        "checks": ["explicação direta", "sem humor no conteúdo", "cita Bronze/Silver/Gold"],
    },
    {
        "id": 3,
        "category": "dados_reais",
        "question": "Quantos casos de SRAG tiveram em dezembro?",
        "checks": ["admite que não tem acesso ao banco", "redireciona pro que pode fazer", "não menciona nomes de tools"],
    },
    {
        "id": 4,
        "category": "limite_claro",
        "question": "Você consegue consultar os dados do banco?",
        "checks": ["resposta clara: não", "não diz 'de forma indireta'", "explica o que pode fazer"],
    },
    {
        "id": 5,
        "category": "tecnica_com_tool",
        "question": "Quais colunas tem a tabela Gold Daily?",
        "checks": ["usa tool internamente", "não menciona nome da tool", "lista colunas"],
    },
    {
        "id": 6,
        "category": "contexto_insuficiente",
        "question": "Me explica a transformação",
        "checks": ["pede mais contexto", "sugere opções específicas"],
    },
    {
        "id": 7,
        "category": "arquivo_especifico",
        "question": "Como configurar o profiles.yml do projeto?",
        "checks": ["usa analyze_code pra ler o arquivo", "cita conteúdo real (databricks, srag_dev, env_var)", "não inventa info genérica"],
    },
]


def _extract_content(result: dict) -> str:
    content = result["messages"][-1].content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    return content if isinstance(content, str) else str(content)


# Agent criado uma vez — conversa multi-turn (todas as perguntas no mesmo thread)
agent = make_agent()
thread_id = str(uuid.uuid4())
config = {"configurable": {"thread_id": thread_id}}

results = []

for q in QUESTIONS:
    print(f"\n{'='*80}")
    print(f"PERGUNTA {q['id']} [{q['category']}]")
    print(f"{'='*80}")
    print(f"{q['question']}")
    print(f"Checks: {q['checks']}")
    print(f"{'-'*80}")

    try:
        result = agent.invoke(
            {"messages": [{"role": "user", "content": q["question"]}]},
            config=config,
        )
        response = _extract_content(result)

        tool_calls = []
        for msg in result["messages"]:
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    tool_calls.append(tc.get("name", "unknown"))

        print(f"\nRESPOSTA:")
        print(response[:800] if response else "(vazio)")
        print(f"\n>>> Tools chamadas: {tool_calls}")

        success = len(response) > 20
        assert success, f"Pergunta {q['id']} ({q['category']}): resposta muito curta ou vazia ({len(response)} chars)"

        results.append({
            "id": q["id"],
            "category": q["category"],
            "tools_called": tool_calls,
            "response_length": len(response),
            "response_preview": response[:200],
            "success": True,
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
print(f"Total: {total} | Respostas: {success_count} | Falha: {total - success_count}")
print()
for r in results:
    status = "OK" if r["success"] else "FALHA"
    tools = ", ".join(r["tools_called"]) if r.get("tools_called") else "nenhuma"
    print(f"  [{status}] Pergunta {r['id']} ({r['category']}): tools=[{tools}]")

assert success_count == total, (
    f"\n{total - success_count}/{total} TESTES FALHARAM:\n" +
    "\n".join(
        f"  - Pergunta {r['id']} ({r['category']}): {r.get('error', 'resposta inválida')}"
        for r in results if not r["success"]
    )
)
print(f"\nTodos os {total} testes passaram.")
