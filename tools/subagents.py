"""Sub-agents implementados como tools com LLM call interno.

Workaround para SubAgentMiddleware incompatível com Gemini.
Cada sub-agent é uma @tool que recebe parâmetros, monta um prompt
especializado, chama o Gemini e retorna o resultado.
"""

import json
import logging
import os
import re
import unicodedata

from langchain.tools import tool
from langchain_google_genai import ChatGoogleGenerativeAI

logger = logging.getLogger(__name__)

_LUPUS_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _sanitize_filename(topic: str) -> str:
    """Converte tópico em nome de arquivo válido em lowercase."""
    name = unicodedata.normalize("NFKD", topic)
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = name.lower()
    name = re.sub(r"[^a-z0-9]+", "_", name)
    name = name.strip("_")[:60]
    return name or "documento"


def _get_project_root() -> str:
    """Retorna o root do projeto via ctx_manager (fonte centralizada)."""
    from core.context_manager import get_project_path
    return get_project_path()


def _get_llm() -> ChatGoogleGenerativeAI:
    """Retorna instância do Gemini para os sub-agents."""
    return ChatGoogleGenerativeAI(model="gemini-2.5-flash")


def _get_domain_tools():
    """Lazy import de domain tools para evitar circular imports.

    Retorna dict com as tools importadas quando chamado.
    """
    from tools.architecture import get_project_architecture
    from tools.dbt_analyzer import analyze_dbt_model
    from tools.lineage import map_data_lineage
    from tools.agent_analyzer import get_agent_tools_spec
    from tools.pipeline_analyzer import analyze_pipeline_config
    from tools.data_dictionary import get_data_dictionary
    from tools.project_discovery import discover_project
    from tools.repository_explorer import explore_repository

    return {
        "get_project_architecture": get_project_architecture,
        "analyze_dbt_model": analyze_dbt_model,
        "map_data_lineage": map_data_lineage,
        "get_agent_tools_spec": get_agent_tools_spec,
        "analyze_pipeline_config": analyze_pipeline_config,
        "get_data_dictionary": get_data_dictionary,
        "discover_project": discover_project,
        "explore_repository": explore_repository,
    }


def _validate_input(value: str, field_name: str, max_length: int = 500, allow_empty: bool = False) -> str | dict:
    """Valida e limpa input de usuário. Retorna erro ou valor limpo.

    Args:
        value: String a validar
        field_name: Nome do campo (para mensagem de erro)
        max_length: Máximo de caracteres permitidos
        allow_empty: Se False, rejeita strings vazias

    Returns:
        String limpa ou dicionário com chave "error" se inválido
    """
    if not isinstance(value, str):
        return {"error": f"'{field_name}' deve ser texto, não {type(value).__name__}."}

    value = value.strip()

    if not allow_empty and not value:
        return {"error": f"'{field_name}' não pode estar vazio."}

    if len(value) > max_length:
        return {"error": f"'{field_name}' excede o máximo de {max_length} caracteres (atual: {len(value)})."}

    return value


def _invoke_with_retry(messages: list[dict], max_retries: int = 2) -> str:
    """Chama o Gemini com retry automático para respostas vazias.

    O Gemini ocasionalmente retorna 0 output tokens (resposta vazia)
    quando o contexto é grande. Um retry simples resolve ~100% dos casos.
    """
    llm = _get_llm()
    for attempt in range(1, max_retries + 1):
        try:
            response = llm.invoke(messages)
        except Exception as e:
            logger.warning("Sub-agent erro na chamada LLM (tentativa %d/%d): %s", attempt, max_retries, e)
            continue
        content = response.content if isinstance(response.content, str) else str(response.content)
        if content and content.strip():
            return content
        logger.warning("Sub-agent retornou resposta vazia (tentativa %d/%d)", attempt, max_retries)
    return json.dumps({"error": f"Sub-agent não obteve resposta após {max_retries} tentativas."}, ensure_ascii=False)


def _read_file_safe(file_path: str) -> str:
    """Lê um arquivo do repositório configurado de forma segura."""
    base = _get_project_root()
    # Normaliza slashes para consistência entre plataformas
    file_path_normalized = file_path.replace("\\", "/").lstrip("./")
    full_path = os.path.normpath(os.path.join(base, file_path_normalized))
    norm_base = os.path.normpath(base)

    # Segurança: não permitir sair do repositório configurado
    try:
        common = os.path.commonpath([full_path, norm_base])
        # Compara paths normalizados (sem mistura de separadores)
        if os.path.normpath(common) != os.path.normpath(norm_base):
            return f"ERRO: Path '{file_path}' está fora do diretório permitido."
    except ValueError:
        return f"ERRO: Path '{file_path}' está fora do diretório permitido."
    if os.path.islink(full_path):
        return f"ERRO: Symlinks não são permitidos: '{file_path}'"

    try:
        with open(full_path, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return f"ERRO: Arquivo '{file_path}' não encontrado."
    except Exception as e:
        return f"ERRO ao ler '{file_path}': {e}"


def _read_file_from_root(project_root: str, file_path: str, max_chars: int = 2500) -> str | None:
    """Lê um arquivo de um project_root arbitrário de forma segura."""
    full_path = os.path.normpath(os.path.join(project_root, file_path))
    norm_root = os.path.normpath(project_root)
    try:
        if os.path.commonpath([full_path, norm_root]) != norm_root:
            return None
    except ValueError:
        return None
    try:
        with open(full_path, encoding="utf-8") as f:
            return f.read(max_chars)
    except Exception:
        return None


# ============================================================
# SUB-AGENT 1: Code Analyzer
# ============================================================

_CODE_ANALYZER_PROMPT = """Você é um analista de código especializado em repositórios técnicos.
Seu trabalho é analisar um arquivo de código específico e responder a pergunta do usuário sobre ele.

Regras:
- Analise APENAS o código fornecido, não invente informação.
- Seja técnico e preciso — cite linhas, funções e variáveis específicas.
- Se o código for SQL, explique transformações, CTEs, joins e lógica de negócio.
- Se o código for Python, explique funções, classes, imports e fluxo de execução.
- Se o código for YAML, explique configurações, parâmetros e seus efeitos.
- Se o código for JavaScript/TypeScript, explique componentes, hooks, exports e fluxo.
- Responda em português, de forma direta e concisa."""


@tool
def analyze_code(file_path: str, question: str) -> str:
    """Sub-agent que analisa um arquivo de código específico do repositório.
    Lê o arquivo e usa IA para responder a pergunta sobre ele.

    Use quando precisar analisar o conteúdo real de um arquivo específico.
    Para perguntas gerais sobre arquitetura ou domínio, use as domain tools primeiro.

    Args:
        file_path: Caminho relativo do arquivo dentro do repositório
                   (ex: 'models/silver/silver_srag_data.sql', 'src/app.py').
        question: Pergunta específica sobre o arquivo."""

    # Validação de inputs
    validated_path = _validate_input(file_path, "file_path", max_length=200)
    if isinstance(validated_path, dict):
        return json.dumps(validated_path, ensure_ascii=False)

    validated_question = _validate_input(question, "question", max_length=500)
    if isinstance(validated_question, dict):
        return json.dumps(validated_question, ensure_ascii=False)

    code = _read_file_safe(validated_path)
    if code.startswith("ERRO"):
        return json.dumps({"error": code}, ensure_ascii=False)

    return _invoke_with_retry([
        {"role": "system", "content": _CODE_ANALYZER_PROMPT},
        {"role": "user", "content": f"## Arquivo: {file_path}\n\n```\n{code}\n```\n\n## Pergunta\n{question}"},
    ])


# ============================================================
# SUB-AGENT 2: Doc Generator
# ============================================================

_DOC_GENERATOR_PROMPT = """Você é um gerador de documentação técnica especializado em repositórios de software e dados.
Seu trabalho é gerar documentação profissional em Markdown sobre um tópico específico do projeto.

Regras:
- Use APENAS as informações fornecidas no contexto. Não invente dados.
- Formate em Markdown profissional com headers, tabelas, listas e code blocks quando relevante.
- Inclua uma seção de resumo no início.
- Seja técnico mas acessível — um desenvolvedor pleno deve entender sem contexto adicional.
- Responda em português.

Regras críticas de conteúdo:
- NÃO adicione seções genéricas de template (Contribuição, Como Contribuir, Licença, Code of Conduct) a menos que o repositório tenha explicitamente esses arquivos ou informações no contexto fornecido.
- Em tabelas, mantenha cada célula CONCISA — no máximo 1-2 frases. Nunca repita conteúdo de outras seções dentro de uma célula de tabela.
- NÃO repita o mesmo conteúdo em seções diferentes. Cada informação aparece uma única vez.
- NÃO invente nomes de arquivos, buckets, variáveis ou configurações que não estejam no contexto.
- Se os arquivos fornecidos não cobrem uma área do projeto (ex: testes, CI/CD), escreva: "Não foram encontrados arquivos de [área] nesta análise." em vez de inventar."""


_DOC_ABNT_PROMPT = """Você é um redator acadêmico especializado em documentação técnica no formato ABNT.
Seu trabalho é gerar um documento acadêmico COMPLETO, EXTENSO e FORMAL sobre o projeto analisado.

O documento será convertido para DOCX posteriormente. Gere o conteúdo em formato YAML estruturado.

## Estrutura obrigatória (todas as seções são OBRIGATÓRIAS):

1. **Introdução** (mínimo 3 parágrafos):
   - Contexto e problemática (por que esse projeto existe, qual problema resolve)
   - Objetivos gerais e específicos do projeto
   - Justificativa técnica e acadêmica
   - Organização do documento

2. **Fundamentação Teórica** (mínimo 4 parágrafos):
   - Conceitos-chave usados no projeto (Data Lake, ETL, Big Data, cloud computing, etc.)
   - Tecnologias e frameworks — explique O QUE são e POR QUE foram escolhidos
   - Estado da arte e referências ao mercado/academia
   - Relação entre os conceitos e o projeto

3. **Metodologia** (mínimo 3 parágrafos):
   - Como o projeto foi planejado e construído
   - Decisões de arquitetura e suas justificativas (por que essa cloud, por que esse formato, etc.)
   - Ferramentas e ambiente de desenvolvimento

4. **Desenvolvimento** (seção mais extensa — mínimo 6 parágrafos):
   - Detalhe CADA componente do projeto separadamente
   - Para cada componente: o que faz, como funciona, quais transformações aplica, entradas e saídas
   - Inclua detalhes técnicos: nomes de funções, campos, tipos de dados, regras de negócio
   - Explique o fluxo completo de dados de ponta a ponta
   - Decisões técnicas específicas (ex: por que Parquet, por que coalesce(1), por que seed fixo)

5. **Resultados e Discussão** (mínimo 3 parágrafos):
   - O que o projeto entrega como output final
   - Análises geradas e o que cada uma revela para o negócio
   - Limitações encontradas e como foram contornadas

6. **Conclusão** (mínimo 2 parágrafos):
   - Síntese das contribuições do projeto
   - Trabalhos futuros e possíveis melhorias

7. **Referências**:
   - Liste tecnologias com links oficiais de documentação
   - Formato ABNT para referências web

## Regras de redação:
- Tom FORMAL e ACADÊMICO — terceira pessoa, linguagem técnica, sem coloquialismo
- EXTENSO e DETALHADO — cada seção deve ter profundidade real, não resumos superficiais
- Use TODAS as informações do contexto — não deixe dados de fora
- NÃO invente dados que não estão no contexto
- Responda em português brasileiro
- O documento final deve ter conteúdo suficiente para pelo menos 8-10 páginas em DOCX

## REGRA CRÍTICA — Nomes e termos técnicos:
- Use os nomes EXATOS de campos, funções, variáveis, buckets e análises como aparecem no código-fonte
- NUNCA renomeie, "melhore" ou parafraseie nomes técnicos. Se o campo se chama `data_entrada`, escreva `data_entrada` — NÃO escreva `data_abertura`, `data_inicio` ou qualquer variação
- Se uma análise se chama `clientes_recorrentes`, escreva `clientes_recorrentes` — NÃO invente `clientes_mais_fieis`
- Se o ID se chama `mov_id`, escreva `mov_id` — NÃO escreva `movimentacao_id`
- Na dúvida, copie o nome literal do contexto. Precisão > elegância

## Formato de saída YAML:
```yaml
titulo: "Título do Projeto"
subtitulo: "Subtítulo descritivo"
secoes:
  - titulo: "1. Introdução"
    conteudo: |
      Texto completo da seção aqui...
  - titulo: "2. Fundamentação Teórica"
    conteudo: |
      Texto completo...
```
Gere o YAML completo com TODO o conteúdo textual dentro de cada seção."""


@tool
def generate_documentation(topic: str, output_filename: str = "", style: str = "tecnico") -> str:
    """Sub-agent que gera documentação técnica sobre um tópico do projeto.
    Lê os arquivos do repositório diretamente e gera documentação completa.
    Salva automaticamente o arquivo em generated_docs/ e no repositório analisado.

    Use quando o usuário pedir para gerar, criar ou escrever documentação sobre
    algum aspecto do projeto analisado (README, arquitetura, pipeline, etc.).

    Args:
        topic: Tópico da documentação (ex: 'README completo', 'arquitetura',
               'pipeline de dados', 'dicionário de dados').
        output_filename: Nome do arquivo de saída (ex: 'readme.md', 'documento.yml').
                        Se vazio, gera nome automaticamente a partir do tópico.
                        Extensões suportadas: .md, .yml, .yaml, .txt
        style: Estilo da documentação. Opções:
               - 'tecnico' (default): Markdown técnico conciso para README/docs
               - 'abnt': Documento acadêmico formal ABNT em formato YAML, extenso
                         e detalhado (mínimo 8-10 páginas). Use para trabalhos
                         acadêmicos, relatórios formais, TCCs, projetos integradores."""

    # Validação de inputs
    validated_topic = _validate_input(topic, "topic", max_length=200)
    if isinstance(validated_topic, dict):
        return json.dumps(validated_topic, ensure_ascii=False)

    validated_style = _validate_input(style, "style", max_length=50)
    if isinstance(validated_style, dict):
        return json.dumps(validated_style, ensure_ascii=False)

    if validated_style not in ("tecnico", "abnt"):
        return json.dumps(
            {"error": f"Style '{validated_style}' inválido. Use 'tecnico' ou 'abnt'."},
            ensure_ascii=False
        )

    if output_filename:
        validated_filename = _validate_input(output_filename, "output_filename", max_length=100)
        if isinstance(validated_filename, dict):
            return json.dumps(validated_filename, ensure_ascii=False)
        # Valida extensão
        if not any(validated_filename.lower().endswith(ext) for ext in [".md", ".yml", ".yaml", ".txt"]):
            return json.dumps(
                {"error": "output_filename deve ter extensão .md, .yml, .yaml ou .txt"},
                ensure_ascii=False
            )
    else:
        validated_filename = ""

    project_root = _get_project_root()
    tools = _get_domain_tools()

    # 1. Coleta contexto lendo arquivos diretamente (sem depender de domain tools)
    discovery_raw = tools["discover_project"].invoke({})
    discovery = json.loads(discovery_raw)
    technologies = discovery.get("technologies", {})

    context_parts = [f"## Tecnologias Detectadas\n{json.dumps({k: v for k, v in technologies.items() if v.get('found')}, ensure_ascii=False, indent=2)}"]

    # Lê arquivos-chave do repo diretamente (I/O puro, sem LLM)
    explore_raw = tools["explore_repository"].invoke({"max_depth": 3})
    explore_data = json.loads(explore_raw)
    all_files = explore_data.get("files", [])
    key_files = explore_data.get("key_files", [])

    readable_types = {"python", "javascript", "typescript", "sql", "config",
                      "markdown", "docker", "shell"}
    code_files = [f["path"] for f in all_files if f.get("type") in readable_types]
    ordered = key_files + [f for f in code_files if f not in key_files]

    char_limit = 30_000 if style.strip().lower() == "abnt" else 15_000
    total_chars = 0
    for fpath in ordered:
        if total_chars >= char_limit:
            break
        content = _read_file_from_root(project_root, fpath)
        if content:
            context_parts.append(f"## {fpath}\n```\n{content}\n```")
            total_chars += len(content)

    # Estrutura de diretórios
    context_parts.append(f"## Estrutura\n{json.dumps(explore_data.get('directories', {}), ensure_ascii=False, indent=2)}")

    # Domain tools opcionais (só se o projeto tiver dbt/databricks/notebooks)
    has_dbt = technologies.get("dbt", {}).get("found", False)
    has_databricks = technologies.get("databricks_asset_bundles", {}).get("found", False)
    has_notebooks = technologies.get("jupyter_notebooks", {}).get("found", False)

    if has_dbt or has_databricks or has_notebooks:
        try:
            context_parts.append(f"## Arquitetura\n{tools['get_project_architecture'].invoke({})}")
        except Exception:
            pass  # falha silenciosa intencional: domain tools são enriquecimento opcional
    if has_dbt:
        try:
            context_parts.append(f"## Linhagem\n{tools['map_data_lineage'].invoke({})}")
        except Exception:
            pass  # falha silenciosa intencional: domain tools são enriquecimento opcional

    context = "\n\n".join(context_parts)

    # 2. Seleciona prompt e extensão baseado no style
    style_lower = style.strip().lower()
    if style_lower == "abnt":
        system_prompt = _DOC_ABNT_PROMPT
        default_ext = ".yml"
        user_prompt = f"Gere um documento acadêmico ABNT completo e extenso sobre: **{topic}**\n\n# Contexto do projeto\n\n{context}"
    else:
        system_prompt = _DOC_GENERATOR_PROMPT
        default_ext = ".md"
        user_prompt = f"Gere documentação técnica sobre: **{topic}**\n\n# Contexto do projeto\n\n{context}"

    content = _invoke_with_retry([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ])

    # 3. Salva o arquivo
    allowed_extensions = {".md", ".yml", ".yaml", ".txt"}
    filename = validated_filename.strip() if validated_filename else (_sanitize_filename(validated_topic) + default_ext)
    filename = os.path.basename(filename)  # impede path traversal (ex: "../../etc/file")
    _, ext = os.path.splitext(filename)
    if ext.lower() not in allowed_extensions:
        filename += default_ext

    saved_paths = []

    def _safe_write(directory: str, fname: str, content: str) -> str | None:
        """Salva arquivo sem sobrescrever — adiciona sufixo _N se já existir."""
        os.makedirs(directory, exist_ok=True)
        base, ext = os.path.splitext(fname)
        candidate = os.path.join(directory, fname)
        counter = 1
        while os.path.exists(candidate):
            candidate = os.path.join(directory, f"{base}_{counter}{ext}")
            counter += 1
        try:
            with open(candidate, "w", encoding="utf-8") as f:
                f.write(content)
            return candidate
        except OSError:
            return None

    # Salva em generated_docs/ (Lupus)
    docs_dir = os.path.join(_LUPUS_ROOT, "generated_docs")
    docs_path = _safe_write(docs_dir, filename, content)
    if docs_path:
        saved_paths.append(os.path.relpath(docs_path, _LUPUS_ROOT).replace("\\", "/"))

    # Salva também no repositório analisado
    if os.path.isdir(project_root) and project_root != _LUPUS_ROOT:
        repo_path = _safe_write(project_root, filename, content)
        if repo_path:
            saved_paths.append(repo_path.replace("\\", "/"))

    save_info = f"\n\n[Documento salvo em: {', '.join(saved_paths)}]" if saved_paths else ""
    return content + save_info


# ============================================================
# SUB-AGENT 3: Architecture Reviewer
# ============================================================

_ARCH_REVIEWER_PROMPT = """Você é um revisor de arquitetura especializado em sistemas de dados e software.
Seu trabalho é analisar decisões de design e padrões arquiteturais, explicando o "por que" por trás de cada escolha.

Regras:
- Fundamente suas análises APENAS nas informações fornecidas.
- Avalie trade-offs: o que a decisão ganha e o que perde.
- Compare com alternativas quando relevante (ex: "poderia ter usado X, mas Y foi escolhido porque...").
- Identifique pontos fortes e possíveis melhorias.
- Seja crítico mas construtivo — aponte problemas com sugestões de solução.
- Responda em português."""


@tool
def review_architecture(question: str) -> str:
    """Sub-agent que faz análise profunda de decisões de design e padrões arquiteturais.
    Cruza informações de múltiplas fontes para responder perguntas do tipo "por que".

    Use quando o usuário fizer perguntas sobre decisões de design, trade-offs,
    padrões arquiteturais, ou pedir uma revisão/crítica da arquitetura.

    Args:
        question: Pergunta sobre arquitetura ou decisão de design
                  (ex: 'por que o bronze é ephemeral?', 'quais os trade-offs do liquid clustering?')."""

    # Validação de input
    validated_question = _validate_input(question, "question", max_length=500)
    if isinstance(validated_question, dict):
        return json.dumps(validated_question, ensure_ascii=False)

    # Descobrir o que existe no projeto para coletar o contexto certo
    tools = _get_domain_tools()
    discovery_raw = tools["discover_project"].invoke({})
    discovery = json.loads(discovery_raw)
    technologies = discovery.get("technologies", {})

    has_dbt = technologies.get("dbt", {}).get("found", False)
    has_databricks = technologies.get("databricks_asset_bundles", {}).get("found", False)
    has_notebooks = technologies.get("jupyter_notebooks", {}).get("found", False)

    context_parts = []
    question_lower = question.lower()

    if has_dbt or has_databricks or has_notebooks:
        context_parts.append(f"## Arquitetura Geral\n{tools['get_project_architecture'].invoke({})}")

    if has_dbt:
        context_parts.append(f"## Linhagem de Dados\n{tools['map_data_lineage'].invoke({})}")

    if has_databricks:
        context_parts.append(f"## Pipeline\n{tools['analyze_pipeline_config'].invoke({})}")

    if has_dbt and any(kw in question_lower for kw in ["modelo", "dbt", "bronze", "silver", "gold", "sql", "materializ"]):
        context_parts.append(f"## Dicionário de Dados\n{tools['get_data_dictionary'].invoke({})}")

    if has_notebooks and any(kw in question_lower for kw in ["agent", "agente", "llm", "tool", "guardrail", "react"]):
        context_parts.append(f"## AI Agent\n{tools['get_agent_tools_spec'].invoke({})}")

    # Fallback
    if not context_parts:
        context_parts.append(f"## Estrutura do Projeto\n{discovery_raw}")

    context = "\n\n".join(context_parts)

    return _invoke_with_retry([
        {"role": "system", "content": _ARCH_REVIEWER_PROMPT},
        {"role": "user", "content": f"## Pergunta de Arquitetura\n{question}\n\n# Contexto do projeto\n\n{context}"},
    ])


# ============================================================
# SUB-AGENT 4: Improvement Suggester
# ============================================================

_IMPROVEMENT_PROMPT = """Você é um AI Engineer senior fazendo code review de um repositório.
Seu trabalho é identificar melhorias técnicas concretas, priorizadas e baseadas em evidências reais do código/configuração fornecido.

Estruture as sugestões nas seguintes categorias (omita as que não tiverem sugestões reais):

## Arquitetura e Design
## Testes e Qualidade de Código
## Observabilidade e Logging
## Segurança e Validação de Dados
## Performance e Escalabilidade
## Documentação
## CI/CD e Automação

Para cada sugestão:
- **Problema ou oportunidade**: o que foi identificado no repositório
- **Por que importa**: impacto real se não for endereçado
- **Como implementar**: ação concreta e específica (não genérica)
- **Prioridade**: Alta / Média / Baixa

Regras:
- Baseie CADA sugestão em evidências do contexto fornecido — cite arquivos, configs ou padrões que você viu.
- Não invente problemas genéricos que se aplicariam a qualquer projeto. Seja específico.
- Use boas práticas das tecnologias identificadas: {tech_list}
- Se uma categoria não tiver sugestões fundamentadas, omita-a completamente.
{focus_instruction}"""


@tool
def suggest_improvements(focus: str = "") -> str:
    """Sub-agent que analisa o repositório e sugere melhorias técnicas priorizadas.

    Examina estrutura, configurações e arquivos-chave para identificar oportunidades
    de melhoria em: arquitetura, testes, observabilidade, segurança, performance,
    documentação e CI/CD.

    Cada sugestão é baseada em evidências reais do repositório — não em
    recomendações genéricas. Referencia boas práticas das tecnologias identificadas.

    Use quando o usuário quiser uma análise crítica do projeto, revisão técnica
    ou sugestões concretas de evolução.

    Args:
        focus: Área específica de foco (ex: 'arquitetura', 'testes', 'segurança',
               'performance', 'documentação', 'ci/cd'). Vazio = análise completa.
    """
    # Validação de input
    if focus:
        validated_focus = _validate_input(focus, "focus", max_length=100)
        if isinstance(validated_focus, dict):
            return json.dumps(validated_focus, ensure_ascii=False)
    else:
        validated_focus = ""

    # 1. Descobrir stack
    tools = _get_domain_tools()
    discovery_raw = tools["discover_project"].invoke({})
    discovery = json.loads(discovery_raw)

    if "error" in discovery:
        return json.dumps({"error": discovery["error"]}, ensure_ascii=False)

    project_root = discovery.get("project_root", "")
    technologies = discovery.get("technologies", {})

    # 2. Estrutura do repositório (profundidade 2 para não sobrecarregar contexto)
    structure_raw = tools["explore_repository"].invoke({"max_depth": 2})
    structure = json.loads(structure_raw)

    # 3. Montar lista de tecnologias detectadas
    tech_list = []
    tech_map = {
        "dbt": "dbt",
        "databricks_asset_bundles": "Databricks Asset Bundles",
        "jupyter_notebooks": "Jupyter Notebooks",
        "go": "Go",
        "java": "Java",
        "terraform": "Terraform",
        "kubernetes": "Kubernetes",
        "docker": "Docker",
    }
    for key, label in tech_map.items():
        if technologies.get(key, {}).get("found"):
            tech_list.append(label)

    if technologies.get("python", {}).get("found"):
        framework = technologies["python"].get("framework")
        tech_list.append(f"Python ({framework})" if framework else "Python")

    if technologies.get("nodejs", {}).get("found"):
        framework = technologies["nodejs"].get("framework")
        tech_list.append(f"Node.js ({framework})" if framework else "Node.js")

    # 4. Ler arquivos-chave para embasar as sugestões
    key_files = structure.get("key_files", [])
    context_files: dict[str, str] = {}

    for key_file in key_files[:10]:
        content = _read_file_from_root(project_root, key_file)
        if content:
            context_files[key_file] = content

    # 5. Montar contexto para o LLM
    context_parts = [
        f"## Tecnologias Detectadas\n{json.dumps({k: v for k, v in technologies.items() if v.get('found')}, ensure_ascii=False, indent=2)}",
        f"## Estrutura de Diretórios\n{json.dumps(structure.get('directories', {}), ensure_ascii=False, indent=2)}",
        f"## Sumário de Arquivos por Tipo\n{json.dumps(structure.get('type_summary', {}), ensure_ascii=False)}",
    ]

    for fname, content in context_files.items():
        context_parts.append(f"## {fname}\n```\n{content}\n```")

    context = "\n\n".join(context_parts)

    focus_instruction = (
        f"\nFoco desta análise: **{validated_focus}** — concentre as sugestões nessa área."
        if validated_focus else ""
    )

    prompt = _IMPROVEMENT_PROMPT.format(
        tech_list=", ".join(tech_list) if tech_list else "não identificadas automaticamente",
        focus_instruction=focus_instruction,
    )

    return _invoke_with_retry([
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"# Contexto do Repositório\n\n{context}"},
    ])


# Export dos sub-agents
SUBAGENT_TOOLS = [analyze_code, generate_documentation, review_architecture, suggest_improvements]
