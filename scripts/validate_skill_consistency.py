#!/usr/bin/env python3
"""Valida consistência entre SKILL.md e config.py.

Garante que instruções chave não contradizem entre os dois arquivos.
"""

import re
import sys
from pathlib import Path

# Diretório raiz do projeto
ROOT = Path(__file__).parent.parent

SKILL_PATH = ROOT / "skills" / "lupus" / "SKILL.md"
CONFIG_PATH = ROOT / "config.py"


def extract_rules_from_skill() -> dict[str, list[str]]:
    """Extrai regras principais do SKILL.md."""
    with open(SKILL_PATH, encoding="utf-8") as f:
        content = f.read()

    rules = {
        "persona": [],
        "execution": [],
        "data_access": [],
        "language": [],
    }

    # Persona (nome, papel, especialidades)
    if "**Nome**: Lupus" in content:
        rules["persona"].append("Nome: Lupus")
    if "AI Engineer" in content:
        rules["persona"].append("Papel: AI Engineer")

    # Execution (Nunca, Sempre, rules)
    execution_section = re.search(
        r"## Execução Contínua.*?(?=##|\Z)", content, re.DOTALL
    )
    if execution_section:
        exec_text = execution_section.group(0)
        if "NUNCA escreva texto antes" in exec_text:
            rules["execution"].append("No text before tool calls")
        if "NUNCA peça confirmação" in exec_text:
            rules["execution"].append("No confirmation between steps")
        if "analyze_full_repository" in exec_text:
            rules["execution"].append("Use analyze_full_repository for URLs")

    # Data access
    data_section = re.search(
        r"## Limites de acesso a dados.*?(?=##|\Z)", content, re.DOTALL
    )
    if data_section:
        data_text = data_section.group(0)
        if "nunca afirme ter acesso" in data_text.lower():
            rules["data_access"].append(
                "Only access data physically in repo"
            )

    # Language
    if "português" in content.lower() or "portuguese" in content.lower():
        if "brasileiro" in content.lower() or "br" in content.lower():
            rules["language"].append("Portuguese BR")
        else:
            rules["language"].append("Portuguese BR")  # Default to BR

    return rules


def extract_rules_from_config() -> dict[str, list[str]]:
    """Extrai regras principais do config.py SYSTEM_PROMPT."""
    with open(CONFIG_PATH, encoding="utf-8") as f:
        content = f.read()

    # Extract SYSTEM_PROMPT
    prompt_match = re.search(
        r'SYSTEM_PROMPT = """(.*?)"""', content, re.DOTALL
    )
    if not prompt_match:
        return {}

    prompt = prompt_match.group(1)

    rules = {
        "persona": [],
        "execution": [],
        "data_access": [],
        "language": [],
    }

    # Persona
    if "Lupus" in prompt and "AI Engineer" in prompt:
        rules["persona"].append("Nome: Lupus")
        rules["persona"].append("Papel: AI Engineer")

    # Execution
    if "NUNCA mencione nomes internos" in prompt:
        rules["execution"].append("No tool names in responses")
    if "analyze_full_repository" in prompt:
        rules["execution"].append("Use analyze_full_repository for URLs")
    if "NUNCA peça confirmação" in prompt or "sem pedir confirmação" in prompt:
        rules["execution"].append("No confirmation between steps")

    # Data access
    if "dados que estão fisicamente" in prompt or "não tem acesso" in prompt:
        rules["data_access"].append("Only access data physically in repo")

    # Language
    if "português" in prompt.lower() or "portuguese" in prompt.lower():
        if "brasileiro" in prompt.lower() or "br" in prompt.lower():
            rules["language"].append("Portuguese BR")
        else:
            rules["language"].append("Portuguese BR")  # Default to BR

    return rules


def validate_consistency() -> bool:
    """Valida que regras chave não contradizem.

    Returns: True se tudo OK, False se há conflitos.
    """
    skill_rules = extract_rules_from_skill()
    config_rules = extract_rules_from_config()

    print("=" * 70)
    print("SKILL.md x config.py CONSISTENCY CHECK")
    print("=" * 70)

    all_ok = True

    for category in ["persona", "execution", "data_access", "language"]:
        skill_set = set(skill_rules.get(category, []))
        config_set = set(config_rules.get(category, []))

        print(f"\n[{category.upper()}]")
        print(f"  SKILL.md:  {skill_set or '(empty)'}")
        print(f"  config.py: {config_set or '(empty)'}")

        if not skill_set and not config_set:
            print("  ✅ Both empty (OK)")
        elif skill_set == config_set:
            print("  ✅ Consistent")
        elif skill_set and config_set and (skill_set & config_set):
            # Overlap OK, não precisa ser 100% igual
            missing_in_config = skill_set - config_set
            missing_in_skill = config_set - skill_set
            if missing_in_config:
                print(f"  ⚠️  Missing in config.py: {missing_in_config}")
            if missing_in_skill:
                print(f"  ⚠️  Extra in config.py: {missing_in_skill}")
            print("  (Partial overlap is OK if not contradictory)")
        else:
            print("  ❌ MISMATCH - contradicting rules!")
            all_ok = False

    print("\n" + "=" * 70)
    if all_ok:
        print("✅ CONSISTENCY OK")
        print("\nRecommendation: No immediate action needed.")
        print("Future changes: Update BOTH files if modifying core rules.")
    else:
        print("❌ CONSISTENCY ISSUES FOUND")
        print("\nAction required: Review and sync the conflicting sections above.")

    print("=" * 70)

    return all_ok


if __name__ == "__main__":
    ok = validate_consistency()
    sys.exit(0 if ok else 1)
