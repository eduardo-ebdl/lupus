"""Bloco 5: Geração automática de 5 documentos via sub-agent generate_documentation.

Chama o sub-agent diretamente (sem o agent principal) para cada tópico,
salvando o resultado em generated_docs/.
"""

import os
import sys
import time

# Path setup — must be before project imports
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, PROJECT_ROOT)
os.chdir(PROJECT_ROOT)

from dotenv import load_dotenv

load_dotenv()

from tools.subagents import generate_documentation

DOCS = [
    {
        "filename": "architecture.md",
        "topic": "Arquitetura geral do projeto, incluindo módulos, camadas, padrões adotados, pipeline de orquestração e fluxo de dados",
    },
    {
        "filename": "module_analysis.md",
        "topic": "Análise dos principais módulos e componentes do projeto: responsabilidades, entradas, saídas e interdependências",
    },
    {
        "filename": "design_patterns.md",
        "topic": "Padrões de design e decisões arquiteturais do projeto: quais padrões foram adotados, por que foram escolhidos e quais trade-offs envolvem",
    },
    {
        "filename": "data_lineage.md",
        "topic": "Linhagem de dados completa do projeto: origem dos dados, transformações aplicadas em cada etapa e destino final",
    },
    {
        "filename": "tech_stack.md",
        "topic": "Stack tecnológico do projeto: linguagens, frameworks, dependências principais, infraestrutura e ferramentas de observabilidade",
    },
]

OUTPUT_DIR = os.path.join(PROJECT_ROOT, "generated_docs")
os.makedirs(OUTPUT_DIR, exist_ok=True)

results = []

for doc in DOCS:
    print(f"\n{'='*60}")
    print(f"Gerando: {doc['filename']}")
    print(f"Tópico: {doc['topic'][:80]}...")
    print(f"{'='*60}")

    start = time.time()

    try:
        content = generate_documentation.invoke({"topic": doc["topic"]})
        elapsed = time.time() - start

        # Remove metadata interna "[Documento salvo em: ...]" que a tool anexa
        if content and "\n\n[Documento salvo em:" in content:
            content = content[:content.index("\n\n[Documento salvo em:")]

        if content and len(content) > 100:
            filepath = os.path.join(OUTPUT_DIR, doc["filename"])
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"OK — {len(content)} chars, {elapsed:.1f}s")
            results.append({"file": doc["filename"], "chars": len(content), "time": elapsed, "success": True})
        else:
            print(f"FALHA — resposta curta demais ({len(content) if content else 0} chars)")
            results.append({"file": doc["filename"], "chars": len(content) if content else 0, "time": elapsed, "success": False})

    except Exception as e:
        elapsed = time.time() - start
        print(f"ERRO — {e} ({elapsed:.1f}s)")
        results.append({"file": doc["filename"], "chars": 0, "time": elapsed, "success": False, "error": str(e)})

# Resumo
print(f"\n{'='*60}")
print("RESUMO")
print(f"{'='*60}")
total = len(results)
success = sum(1 for r in results if r["success"])
total_chars = sum(r["chars"] for r in results)
total_time = sum(r["time"] for r in results)
print(f"Total: {total} | Sucesso: {success} | Falha: {total - success}")
print(f"Total chars: {total_chars:,} | Tempo total: {total_time:.1f}s")
print()
for r in results:
    status = "OK" if r["success"] else "FALHA"
    print(f"  [{status}] {r['file']}: {r['chars']:,} chars, {r['time']:.1f}s")
