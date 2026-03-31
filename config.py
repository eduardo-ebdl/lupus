"""Configuração central do Lupus.

SYSTEM_PROMPT e make_agent() compartilhados por main.py, testes e avaliação.
Garante que o agente se comporta identicamente em todos os contextos.
"""

import atexit
import os
import sqlite3

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.agents import create_agent
from langchain.agents.middleware import TodoListMiddleware
from deepagents.middleware.filesystem import FilesystemMiddleware
from deepagents.middleware.patch_tool_calls import PatchToolCallsMiddleware
from deepagents.middleware.memory import MemoryMiddleware
from deepagents.middleware.skills import SkillsMiddleware
from deepagents.backends import FilesystemBackend
from langgraph.checkpoint.sqlite import SqliteSaver

from core.context_manager import ctx_manager
from tools import ALL_TOOLS

load_dotenv()

# Validação de variáveis obrigatórias
if not os.getenv("GOOGLE_API_KEY"):
    raise ValueError(
        "GOOGLE_API_KEY não definida. Configure no arquivo .env ou como variável de ambiente."
    )

# LangSmith — ativado automaticamente pelo LangChain quando LANGCHAIN_TRACING_V2=true
# está definido no .env. Nenhum código adicional necessário — o load_dotenv() acima
# injeta as variáveis e o LangChain detecta. Ver .env.example para configuração.

# Contexto máximo por análise (bytes) — configurável via env var LUPUS_MAX_CONTEXT_BYTES
# Padrão: 8000 bytes (8 KB). Aumentar para análises maiores, mas cuidado com timeouts.
try:
    _MAX_CONTEXT_BYTES_STR = os.getenv("LUPUS_MAX_CONTEXT_BYTES", "8000")
    MAX_CONTEXT_BYTES = int(_MAX_CONTEXT_BYTES_STR)
    if MAX_CONTEXT_BYTES > 50000:
        import logging as _logging
        _logging.getLogger(__name__).warning(
            f"MAX_CONTEXT_BYTES={MAX_CONTEXT_BYTES} é muito alto (>50KB). "
            "Análises podem ficar lentas ou causar timeout. Recomendado: ≤20KB."
        )
except (ValueError, TypeError):
    MAX_CONTEXT_BYTES = 8000
    import logging as _logging
    _logging.getLogger(__name__).warning(
        f"LUPUS_MAX_CONTEXT_BYTES inválido: '{_MAX_CONTEXT_BYTES_STR}'. Usando padrão: 8000 bytes."
    )

# Diretório raiz do projeto (onde este arquivo está)
_ROOT = os.path.dirname(os.path.abspath(__file__))

# Inicializa ctx_manager a partir de env var ou demo padrão.
# Registra hooks para invalidar cache e RAG quando o repositório muda.
_DEFAULT_PROJECT = os.path.join(_ROOT, "srag_agent")
ctx_manager.init_from_env(default_path=_DEFAULT_PROJECT)

from tools.cache import on_repo_change as _cache_on_repo_change
from tools.rag_search import on_repo_change as _rag_on_repo_change
ctx_manager.register_hook(_cache_on_repo_change)
ctx_manager.register_hook(_rag_on_repo_change)

# Persistência de conversas via SQLite (sobrevive a reinícios do processo)
# Nota: _checkpointer é criado globalmente apenas para compatibilidade com main.py
# Novos usos de make_agent() devem injetar checkpointer explicitamente
_DB_DIR = os.path.join(os.path.expanduser("~"), ".lupus")
_DB_PATH = os.path.join(_DB_DIR, "conversations.db")
_db_conn = None
_checkpointer = None


def get_checkpointer():
    """Obtém ou cria o checkpointer SQLite global.

    Lazy initialization: a conexão é criada apenas quando get_checkpointer() é chamado.
    Isso permite testes injetar mock checkpointers sem poluir o filesystem.

    Returns:
        SqliteSaver: Instância de checkpointer SQLite para persistência de conversas.
    """
    global _db_conn, _checkpointer

    if _checkpointer is None:
        os.makedirs(_DB_DIR, exist_ok=True)
        _db_conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
        atexit.register(_db_conn.close)
        _checkpointer = SqliteSaver(conn=_db_conn)

    return _checkpointer

# System prompt canônico — usado por main.py, testes e avaliação
# NOTA: Este prompt deve estar em sync com skills/lupus/SKILL.md
# Valide com: python scripts/validate_skill_consistency.py
SYSTEM_PROMPT = """Você é o Lupus, AI Engineer especializado em análise técnica de repositórios.
Leia o SKILL.md do lupus e siga RIGOROSAMENTE suas instruções de persona, tom e limites.

MODO DE OPERAÇÃO:
- Se o usuário NÃO configurou repositório: responda naturalmente, de forma conversacional. NÃO tente usar tools. Sugira que configure um repositório com /repo <URL>.
- Se o usuário configurou repositório: use tools quando apropriado para análise técnica.

Regras críticas:
- NUNCA mencione nomes internos de tools na resposta ao usuário. Descreva o que fez: "consultei o dicionário de dados", não "chamei get_data_dictionary".
- Acesso a dados: você só tem acesso a dados que estão fisicamente no repositório (ex: arquivos CSV, JSON, Parquet). Dados em sistemas externos (banco de dados, cloud) não estão disponíveis — você pode explicar como são processados, mas não retorna valores reais.
- Quando a pergunta for vaga, peça contexto específico antes de responder.
- Quando a pergunta for sobre estrutura, tecnologias ou arquitetura geral do repositório, chame discover_project PRIMEIRO.
- Quando a pergunta for sobre um arquivo específico, use analyze_code para lê-lo ANTES de responder. NUNCA responda sobre arquivos usando conhecimento geral.
- Use MÚLTIPLAS tools quando a pergunta cruzar temas.
- Quando o usuário pedir análise completa ou aprofundada, execute TODAS as tools necessárias em sequência sem pedir confirmação entre etapas. Entregue o resultado consolidado de uma vez. NÃO anuncie planos antes de executar — faça e apresente.
- Quando receber uma URL de repositório GitHub, chame analyze_full_repository (NÃO clone_repository). Esta tool clona, explora e lê os arquivos automaticamente. Com o resultado, gere a análise completa.
- Quando o usuário pedir para gerar documentação ou README, chame generate_documentation com o tópico e output_filename. A tool salva o arquivo automaticamente — NÃO diga que salvou se a tool não confirmou.
- Quando descrever camadas, componentes ou módulos, explique a função de cada um. Não liste apenas nomes.
- Raciocine antes de responder: verifique se o que vai entregar está fundamentado e faz sentido.
- SEMPRE termine sua resposta com uma sugestão contextual e específica do que o usuário pode fazer a seguir (ex: "Posso analisar o X ou gerar documentação sobre Y. Qual prefere?"). NUNCA use frases genéricas como "me avise se precisar de mais algo". Exceção: se o usuário pediu explicitamente para não sugerir nada.
- Responda em português brasileiro."""


def make_agent(system_prompt: str = SYSTEM_PROMPT, checkpointer=None):
    """Cria uma instância do agent Lupus com todos os middlewares.

    Por padrão usa SqliteSaver para persistir conversas entre sessões (~/.lupus/conversations.db).
    Para conversas multi-turn, reutilize o mesmo agent com thread_ids distintos.

    Args:
        system_prompt: System prompt a usar. Padrão: SYSTEM_PROMPT canônico.
        checkpointer: Instância de checkpointer (ex: SqliteSaver ou MockCheckpointer).
                     Se None, usa get_checkpointer() para obter a instância global.
                     Testes devem injetar MockCheckpointer aqui para evitar I/O de filesystem.

    Returns:
        Agent: Instância do agente LangGraph com middlewares configurados.
    """
    if checkpointer is None:
        checkpointer = get_checkpointer()

    llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash")

    # Lê path do ctx_manager (atualizado automaticamente por clone_repository)
    current_project_path = ctx_manager.path or _DEFAULT_PROJECT
    project_backend = FilesystemBackend(
        root_dir=current_project_path, virtual_mode=True
    )
    lupus_backend = FilesystemBackend(root_dir=_ROOT, virtual_mode=True)
    skills_backend = FilesystemBackend(
        root_dir=os.path.join(_ROOT, "skills"), virtual_mode=True
    )

    return create_agent(
        llm,
        system_prompt=system_prompt,
        tools=ALL_TOOLS,
        middleware=[
            TodoListMiddleware(),
            FilesystemMiddleware(backend=project_backend),
            PatchToolCallsMiddleware(),
            MemoryMiddleware(backend=lupus_backend, sources=["AGENTS.md"]),
            SkillsMiddleware(backend=skills_backend, sources=["./lupus/"]),
        ],
        checkpointer=checkpointer,
    )
