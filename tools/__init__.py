"""Tools de domínio, sub-agents e RAG do Lupus para análise de repositórios."""

from tools.project_discovery import discover_project
from tools.repository_explorer import explore_repository
from tools.data_file_reader import read_data_file
from tools.github_integration import clone_repository
from tools.full_analysis import analyze_full_repository
from tools.architecture import get_project_architecture
from tools.dbt_analyzer import analyze_dbt_model
from tools.lineage import map_data_lineage
from tools.agent_analyzer import get_agent_tools_spec
from tools.pipeline_analyzer import analyze_pipeline_config
from tools.data_dictionary import get_data_dictionary
from tools.code_dependencies import map_code_dependencies
from tools.subagents import analyze_code, generate_documentation, review_architecture, suggest_improvements
from tools.rag_search import search_codebase

# Tools de descoberta e mapeamento: entendem o repositório antes de qualquer análise
DISCOVERY_TOOLS = [
    discover_project,
    explore_repository,
    read_data_file,
    clone_repository,
    analyze_full_repository,
]

# Tools de domínio (Bloco 2): leem arquivos reais do projeto
DOMAIN_TOOLS = [
    get_project_architecture,
    analyze_dbt_model,
    map_data_lineage,
    get_agent_tools_spec,
    analyze_pipeline_config,
    get_data_dictionary,
    map_code_dependencies,
]

# Sub-agents (Bloco 3): tools dinâmicas com LLM call interno
SUBAGENT_TOOLS = [
    analyze_code,
    generate_documentation,
    review_architecture,
    suggest_improvements,
]

# RAG (Bloco 8): busca semântica híbrida no codebase real
RAG_TOOLS = [
    search_codebase,
]

# Todas as tools combinadas
ALL_TOOLS = DISCOVERY_TOOLS + DOMAIN_TOOLS + SUBAGENT_TOOLS + RAG_TOOLS
