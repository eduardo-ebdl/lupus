# Backlog — Lupus

Ideias para evolução futura, organizadas por categoria e prioridade estimada.

---


## PORTFÓLIO / CARREIRA

---

### Expor API REST (FastAPI ou LangServe)

**Ideia**: transformar o Lupus de ferramenta CLI em serviço HTTP, permitindo integração com qualquer cliente.

**Por que importa**: hoje o Lupus só funciona com Python instalado e rodando no terminal. Com uma API, qualquer sistema pode integrar — frontend, Slack bot, CI/CD, PR review automático.

**Abordagem**:
- FastAPI com endpoint `POST /chat` e suporte a `thread_id` para multi-turn
- LangServe como alternativa — expõe o agente automaticamente com playground no browser e streaming nativo
- Streaming via Server-Sent Events (SSE)

**Relevância pra mercado**: "desenvolver e manter APIs para acesso e gerenciamento de modelos de IA" — requisito direto em vagas de AI Engineer. Também desbloqueia itens do backlog (Web UI, PR review automático, integrações).

---

### Documentar Arquitetura de Avaliação

**Ideia**: documentar formalmente a metodologia de avaliação do agente — decisões, métricas, resultados e limitações.

**O que já existe**:
- Dataset de 25 perguntas em 5 categorias
- 3 níveis de métricas: keyword accuracy, tool coverage, LLM-as-judge (completude, relevância, fundamentação)
- 96% de accuracy no dataset original
- Retry automático e logging de resultados

**O que documentar**:
- Por que LLM-as-judge em vez de avaliação manual
- Como o dataset foi construído e o que cada categoria mede
- Limitações conhecidas (dataset pequeno, repo fixo, sem avaliação adversarial)
- Como o feedback log se conecta com a avaliação contínua

**Relevância pra mercado**: "propor e coletar métricas para avaliar e melhorar o desempenho dos modelos" — a sofisticação da avaliação é diferencial claro em entrevistas técnicas.

---

## PRIORIDADE ALTA

---

### RAG — Fallback Automático por Mismatch

**Problema**: ao trocar de repositório (via `clone_repository` ou `PROJECT_PATH`), o índice RAG ainda reflete o projeto anterior. O agente pode responder com contexto do repo errado silenciosamente — isso quebra confiança.

**Melhoria**:
- Salvar `repo_id` (hash do PROJECT_PATH) nos metadados do índice ao fazer build
- Em `search_codebase`: comparar PROJECT_PATH atual com `repo_id` salvo
- Se mismatch → ignorar RAG completamente, usar tools diretas como fallback
- Exibir aviso ao usuário: "índice RAG está desatualizado para este repositório"

**Extra**: trigger automático de rebuild quando PROJECT_PATH muda e git detecta diff.

---

### Persistência de Conversas (SqliteSaver)

**Problema**: `InMemorySaver` perde todo o histórico ao encerrar a sessão. `/exportar` salva Markdown mas não permite retomar.

**Abordagem**: substituir `InMemorySaver` por `SqliteSaver` do LangGraph. Cada `thread_id` persistido em `~/.lupus/conversations.db`. Comando `/retomar` lista sessões anteriores.

---

### Simulação de Impacto — "O que quebra?"

**Ideia**: feature `simulate_impact(change_description)` que responde "se eu mudar X, o que é afetado?".

**Como fazer**:
- Cruzar `map_code_dependencies` (quem importa o arquivo/função)
- Cruzar `map_data_lineage` (quais modelos dependem desse dado)
- Montar grafo: Arquivo A → usado por B → usado por C → impacto estimado

**Valor**: diferencial claro, nenhum Copilot faz bem. Implementável com tools existentes.

---

## PRIORIDADE MÉDIA

---

### Modo Onboarding — "Por onde começo?"

**Ideia**: comando `/onboarding` que gera um guia estruturado para um desenvolvedor novo no repositório.

**Diferencial do `generate_documentation`**: orientado para uma pessoa, não para um documento. Foco em sequência de aprendizado, não em cobertura total.

**Fluxo interno**:
1. `discover_project` → entende o stack
2. `explore_repository` → identifica arquivos-chave e entry points reais
3. `map_code_dependencies` → encontra o fluxo principal de execução
4. Síntese em formato guiado:
   - O que é esse projeto e o que faz
   - Como rodar localmente
   - Por onde começar a ler o código
   - Os 3-5 fluxos mais importantes
   - O que ignorar por enquanto

**"O que ignorar por enquanto"** é o diferencial real — nenhuma documentação tradicional faz isso.

**Use case**: dev novo numa empresa clona o repo e pergunta "como entro nesse projeto?".

---

### Modo Professor — Trilha de Aprendizado

**Ideia**: modo de explicação estruturada e progressiva de um repositório, adaptado ao nível do usuário.

**Gap atual**: o Lupus explica bem quando perguntado, mas não tem um fluxo de ensino sequencial.

**Proposta**:
- `/professor` ativa um modo com checkpoints
- Começa pela estrutura macro, aprofunda por módulo
- Pergunta ao usuário se quer mais detalhe antes de avançar
- Adapta linguagem ao nível declarado (iniciante / intermediário / avançado)

**Diferencial**: o que separa Lupus de qualquer Copilot genérico — entende o repo real e ensina a partir dele.

---

### Geração de Testes Automática

**Ideia**: dado um arquivo ou função, gerar testes unitários e de integração baseados no comportamento real do código.

**Como fazer**:
- `analyze_code` lê o arquivo e extrai funções/classes
- Sub-agent gera testes com casos de uso baseados na lógica real
- Segue o padrão de testes já existente no repo (detectado via `explore_repository`)

**Valor**: alto — ninguém faz bem, e é um dos problemas mais concretos de qualquer projeto.

---

### Atualização Incremental do RAG

**Problema**: rebuild do índice é manual e reconstrói tudo do zero.

**Melhoria**:
- Usar `git diff` para detectar arquivos modificados desde a última indexação
- Re-indexar apenas os arquivos alterados
- Salvar timestamp do último build nos metadados

**Impacto**: performance + índice sempre atualizado sem custo total de rebuild.

---

### Exercícios Automáticos — "LeetCode do seu próprio código"

**Ideia**: gerar tasks práticas baseadas no repositório real.

**Exemplos**:
- "Adicione validação nessa função"
- "Refatore esse módulo para reduzir acoplamento"
- "Corrija esse bug injetado"

**Diferencial**: treinamento com código real, não exercícios genéricos. Útil para onboarding e para aprendizado ativo.

**Complexidade**: alta — requer geração + correção automática. Priorizar geração primeiro, correção depois.

---

### PR Review / Diff

**Ideia**: analisar automaticamente o que mudou numa branch e apontar riscos antes do push.

**Abordagem local (MVP)**: git hook `pre-push` que dispara o review automaticamente no `git push`, sem o usuário precisar pedir.

```bash
# .git/hooks/pre-push
python main.py --review  # analisa o diff antes de fazer push
```

**Tool necessária**: `get_git_diff(base="main")` que roda `git diff main...HEAD` no `PROJECT_PATH` automaticamente — sem o usuário colar nada.

**Saída**: riscos por arquivo, dependências afetadas (cruzando com `map_code_dependencies`), sugestões de melhoria.

**Padrão de mercado**: GitHub App com webhook (CodeRabbit, Sourcery, PR-Agent) — posta comentários inline diretamente no PR. Requer OAuth + deploy + API GitHub. Faz sentido se o projeto evoluir para produto.

**Valor**: alto — o git hook já seria diferencial real no escopo atual. GitHub App seria produto de verdade.

---

### Feedback Positivo

**Contexto**: o sistema atual coleta apenas feedback negativo via `/reportar`.

**Ideia**: analisar uma forma de coletar feedback positivo — identificar quais perguntas e combinações de tools geraram respostas aprovadas.

**Possíveis usos**:
- Detectar quais tools têm maior taxa de acerto por tipo de pergunta
- Construir exemplos few-shot positivos para injetar junto com os negativos
- Dataset balanceado para avaliação quantitativa

**Desafio**: coletar positivo sem criar fricção. Possíveis abordagens: inferir positivo quando o usuário continua sem reportar, ou `/bom` como comando opcional.

---

### LangGraph Studio

**Contexto**: desktop app que fornece UI visual para agentes LangGraph — chat interativo, grafo animado em tempo real, inspeção de estado e histórico de tool calls.

**Limitação**: não roda no Windows nativamente. Requer Mac ou Linux com Docker + LangGraph Platform.

**Quando retomar**: quando houver acesso a Mac ou suporte Windows disponível.

**Referência**: [LangGraph Studio](https://github.com/langchain-ai/langgraph-studio)

---

## PRIORIDADE BAIXA

---

### Planner Layer (agente mais explícito)

**Ideia**: adicionar um passo de planejamento antes da execução de tools.

```
User → Planner (decide quais tools + ordem) → Execução → Síntese
```

**Ressalva**: o ReAct já faz planejamento implícito. Sem dado que mostre falha sistemática na escolha de tools, adicionar planner aumenta latência e complexidade sem ROI claro. Reavaliar com base em evidências do feedback log.

---

### Score de Confiança na Resposta

**Ideia**: cada resposta vem com indicador de confiança (alta / média / baixa) baseado em: uso de tools, uso de RAG, fallback para conhecimento geral.

**Ressalva**: "confiança" é difícil de definir com precisão aqui. "Usou RAG" ≠ "confiante". Implementar mal pode ser enganoso. Reavaliar quando houver dados do feedback log para calibrar.

---

### Truncamento de Histórico (trim_messages)

**Contexto**: o agente acumula histórico completo sem limite. Impacto atual baixo — Gemini 2.5 Flash tem 1M tokens de contexto.

**Abordagem**: `langchain_core.messages.trim_messages(messages, max_tokens=...)` ou sumarização automática do histórico antigo.

---

### Análise Multi-Repositório

**Por que foi adiado**: custo de tokens elevado para manter dois contextos. Utilidade questionável — o caso mais comum é comparar ferramentas durante o desenvolvimento, não depois.

**Abordagem quando retomar**: serializar outputs das domain tools dos dois repos para JSON, montar contexto compacto com diffs estruturados.

---

### Web UI (Streamlit / Gradio / Chainlit)

**Ideia**: interface web compartilhável sem instalar Python local. Upload de zip para configurar PROJECT_PATH.

**Alternativa mais leve**: Chainlit integra nativamente com LangGraph e tem streaming nativo.

---

### RAG Multi-Repositório

**Ideia**: índice FAISS único com namespace por projeto (`repo_name` nos metadados). Filtragem por repo no retriever. Build incremental.

---

### Plugin VSCode

**Ideia**: extensão VSCode que abre o Lupus como sidebar com PROJECT_PATH = workspace atual. Zero configuração.

---

### Análise de Dependências Transitivas

**Ideia**: expandir `map_code_dependencies` para resolver imports transitivos (A → B → C). Detectar ciclos, calcular fan-in/fan-out.

---

### Avaliação Contínua (CI)

**Ideia**: rodar `evaluation/run_evaluation.py` no CI (GitHub Actions) a cada PR. Métricas: accuracy@k, tool_hit_rate, latency_p95.

---

### Suporte a Repositórios Privados

**Implementação**: token GitHub/GitLab via `GIT_ASKPASS` ou URL autenticada em `clone_repository`. Token via env var, nunca hardcoded.

---

### Memory Persistente do Agente

**Ideia**: salvar fatos aprendidos sobre o repositório entre sessões. `MemoryTool` que escreve/lê de `~/.lupus/memory/<repo_name>.json`.

---

## RESOLVED

### ✓ HuggingFace warnings suppression
- **Commit**: a966db4
- **Descrição**: Adicionado logging.setLevel(ERROR) para sentence_transformers, transformers e huggingface_hub em main.py e rag/retriever.py
- **Status**: Completo

### ✓ Exception logging in streaming
- **Commit**: a966db4
- **Descrição**: Adicionado logger.exception() em main.py para capturar erros de streaming ao invés de silenciá-los
- **Status**: Completo

### ✓ Cache purge timing
- **Commit**: a966db4
- **Descrição**: Cache agora limpa entradas expiradas baseado em tempo (5 minutos) além de count (20 escritas)
- **Status**: Completo
