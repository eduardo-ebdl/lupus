# Lupus — Guia de Manutenção

Documentação para contribuidores que modificam regras, comportamento ou configuração do Lupus.

## Arquivos de Persona e Comportamento

Dois arquivos definem como o Lupus funciona:

| Arquivo | Propósito | Escopo |
|---------|-----------|--------|
| `skills/lupus/SKILL.md` | Definição canônica de persona, tom, limites e comportamento | Tudo sobre identidade e princípios |
| `config.py` (SYSTEM_PROMPT) | Prompt de runtime que reforça regras em operação | Regras específicas de tool-calling e operação |

## Garantindo Consistência

### Validação automática
Execute antes de commitar:
```bash
python scripts/validate_skill_consistency.py
```

Status esperado: ✅ CONSISTENCY OK

### Quando modificar qual arquivo

#### SKILL.md — Modifique quando:
- Mudar persona (nome, papel, especialidades)
- Adicionar/remover limites de acesso a dados
- Alterar tom ou estilo de resposta
- Adicionar novas regras de comportamento geral
- Documentar novos padrões de uso

**Exemplo:** "Lupus agora também especialista em Kubernetes"
```markdown
- **Especialidades**: Engenharia de dados, AI Agents, MLOps, arquitetura de software, pipelines de dados, LLMs, Kubernetes
```

#### config.py SYSTEM_PROMPT — Modifique quando:
- Alterar ordem de execução de tools (ex: "sempre chame discover_project primeiro")
- Mudar regras de resposta (ex: "adicione exemplos em toda resposta")
- Adicionar restrições operacionais (ex: "máximo 3 tools por pergunta")
- Definir comportamento especial por tipo de repositório

**Exemplo:** "Adicionar suporte para respostas JSON estruturadas"
```python
- Quando o usuário pedir análise em formato JSON, retorne sempre com estrutura: {"summary": ..., "details": ...}
```

### Checklist para mudanças que afetam ambos

Se sua mudança afeta **identidade OU comportamento**, siga:

1. **Atualize SKILL.md primeiro** (fonte de verdade)
2. **Atualize config.py SYSTEM_PROMPT** para reforçar a regra
3. **Rode validação:**
   ```bash
   python scripts/validate_skill_consistency.py
   ```
4. **Commit com mensagem clara:**
   ```
   feat: Add Kubernetes to Lupus specialties
   
   - Updated SKILL.md persona section
   - Sync'd config.py SYSTEM_PROMPT
   - Validated consistency check passes
   ```

## Estrutura do SKILL.md

```
---
name: lupus
description: ...
metadata:
  version: "X.Y.Z"
  last_updated: "YYYY-MM-DD"
---

# Lupus

## Identidade
  (nome, papel, especialidades, personalidade)

## Princípio central: raciocinar antes de responder
  (decisões mentais antes de responder)

## Execução Contínua — Regras Absolutas
  (regras de tool-calling e fluxo)

## Tom e estilo
  (tom profissional, didático, sem humor forçado)

## Limites de acesso a dados
  (o que Lupus pode/não pode acessar)

## Comportamento por tipo de repositório
  (padrões específicos por tech stack)

## Seleção de tools
  (quando usar qual tool)

## Regras para geração de documentos
  (ao chamar generate_documentation)

## Estado do Repositório
  (gerenciamento de repo e cache)

## O que NÃO fazer
  (anti-padrões e erros comuns)

## Idioma
  (português brasileiro)

## Integração com config.py e Runtime Behavior
  (relação entre os dois arquivos, conflito prevention checklist)
```

## Versioning

Mantenha `metadata.version` no SKILL.md atualizado:

- **Patch (X.Y.Z)** → Bug fixes, wording improvements, não afeta comportamento
- **Minor (X.Y.0)** → Novas regras, novos limites, mas sem quebrar regras existentes  
- **Major (X.0.0)** → Mudanças fundamentais na persona ou princípios

**Exemplo:**
```yaml
metadata:
  version: "1.1.0"  # Added Kubernetes, but didn't break existing rules
  last_updated: "2026-04-15"
```

## Problemas Comuns

### "Fiz mudança em SKILL.md mas o agente não mudou"
→ Isso é esperado. SKILL.md é carregado pelo SkillsMiddleware.
→ Se mudança é operacional (tool-calling), também edite `config.py` SYSTEM_PROMPT.

### "Validation script diz mismatch"
→ Execute: `python scripts/validate_skill_consistency.py`
→ Revise a seção indicada em ambos arquivos
→ Se conflit é intencional, documente no commit message

### "Dois contributors modificaram SKILL.md diferentes seções"
→ Sem problema — ambas mudanças devem ser mergeadas
→ Rode validação após merge para confirmar consistência

## Troubleshooting de Desenvolvimento

### venv prompt mostrando `((venv) )` com espaçamento ruim

**Causa:** Arquivo `venv/Scripts/activate` tem parênteses extras na linha 70.

**Solução:** Edite `venv/Scripts/activate` linha 70:
```bash
# ❌ Incorreto:
PS1="("'(venv) '") ${PS1:-}"

# ✅ Correto:
PS1="${VIRTUAL_ENV_PROMPT}${PS1:-}"
```

Depois reative: `deactivate && source venv/Scripts/activate`

**Por que não está em git:** `venv/` é gerado localmente e está em `.gitignore`. 
Se problema persistir após recriar venv, o arquivo foi corrompido durante criação.

## Próximas Melhorias

- [ ] Adicionar pre-commit hook que roda `validate_skill_consistency.py`
- [ ] GitHub Actions: validação em PRs automaticamente
- [ ] Gerar changelog automático quando `metadata.version` muda
- [ ] Documentar exemplos de persona em diferentes linguagens
- [ ] Template de venv com `activate` pre-corrigido

---

**Última atualização:** 2026-03-31  
**Responsável:** Equipe de manutenção do Lupus
