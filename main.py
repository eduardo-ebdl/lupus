"""Lupus — AI Code Intelligence Agent (CLI Chat)"""

import json
import logging
import os
import time
import uuid
from datetime import datetime

# Suprime warnings de carregamento de pesos do HuggingFace/sentence-transformers
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)

logger = logging.getLogger(__name__)

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from config import make_agent
from core.context_manager import ctx_manager

console = Console()

# Caminhos para hot reload do SKILL.md
_ROOT = os.path.dirname(os.path.abspath(__file__))
_SKILL_PATH = os.path.join(_ROOT, "skills", "lupus", "SKILL.md")


def _get_skill_mtime() -> float:
    """Retorna o mtime do SKILL.md para detecção de mudanças."""
    try:
        return os.path.getmtime(_SKILL_PATH)
    except OSError:
        return 0.0


def _export_conversation(agent, thread_id: str) -> str:
    """Exporta a conversa atual como arquivo Markdown."""
    try:
        state = agent.get_state({"configurable": {"thread_id": thread_id}})
        messages = state.values.get("messages", [])
    except Exception as e:
        return f"Erro ao acessar histórico: {e}"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_dir = os.path.join(_ROOT, "exports")
    os.makedirs(export_dir, exist_ok=True)
    filename = os.path.join(export_dir, f"conversa_{timestamp}.md")

    lines = [
        f"# Conversa com Lupus\n",
        f"**Exportado em:** {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}  ",
        f"**Repositório:** `{ctx_manager.path}`\n",
        "---\n",
    ]

    # Agrupa mensagens consecutivas do Lupus: mantém só a última de cada sequência.
    # Evita que anúncios intermediários ("Vou analisar...") apareçam junto com a
    # resposta real — ambos ficam no estado quando o agente anuncia antes de chamar tools.
    collapsed: list[tuple[str, str]] = []  # [(type, content)]
    for msg in messages:
        msg_type = getattr(msg, "type", "")
        content = getattr(msg, "content", "")
        if not content or msg_type in ("tool", "tool_call"):
            continue
        if isinstance(content, list):
            content = "\n".join(
                block.get("text", "") for block in content if isinstance(block, dict)
            )
        if not isinstance(content, str) or not content.strip():
            continue
        if collapsed and collapsed[-1][0] == "ai" and msg_type == "ai":
            collapsed[-1] = ("ai", content)  # substitui pelo mais recente
        else:
            collapsed.append((msg_type, content))

    for msg_type, content in collapsed:
        if msg_type == "human":
            lines.append(f"\n**Você:** {content}\n")
        elif msg_type == "ai":
            lines.append(f"\n**Lupus:** {content}\n")

    lines.append("\n---\n*Gerado por Lupus*")

    with open(filename, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    return filename


def _format_generated_doc_response(response: str) -> str | None:
    """Detecta e formata respostas de generate_documentation com paths claros.

    Se a resposta for JSON de geração de doc, retorna formatação visual com paths.
    Caso contrário, retorna None para deixar o handler padrão processar.
    """
    try:
        # Tenta parsear como JSON
        if not response.strip().startswith("{"):
            return None

        data = json.loads(response)

        # Verifica se é resposta de geração de documentação
        if data.get("status") not in ("ok", "error") or "saved_to" not in data:
            return None

        # Formata resposta sucesso
        if data.get("status") == "ok":
            paths = data.get("absolute_paths", [])
            filename = data.get("filename", "documento")
            content_preview = data.get("content", "")[:200] + "..." if data.get("content") else ""

            msg = (
                f"[green]✅ Documentação gerada com sucesso[/green]\n\n"
                f"[bold]Arquivo:[/bold] {filename}\n"
                f"[bold]Estilo:[/bold] {data.get('style', 'técnico')}\n\n"
                f"[bold]Localização(ões):[/bold]\n"
            )
            for path in paths:
                msg += f"  📁 [cyan]{path}[/cyan]\n"

            msg += f"\n[dim]Preview:[/dim]\n{content_preview}"
            return msg

        # Formata resposta erro
        else:
            return (
                f"[red]❌ Erro ao gerar documentação[/red]\n\n"
                f"[bold]Problema:[/bold] {data.get('error', 'desconhecido')}\n"
                f"[bold]Arquivo tentado:[/bold] {data.get('filename', 'N/A')}\n"
                f"[dim]Diretórios tentados: {', '.join(data.get('attempted_dirs', []))}[/dim]"
            )
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def _print_banner(repo_name: str):
    """Exibe banner de boas-vindas com instruções de uso."""
    console.print()

    # Texto diferente se tem repositório ativo ou não
    if repo_name:
        repo_text = f"[dim]Repositório ativo: [cyan]{repo_name}[/cyan][/dim]\n\n"
    else:
        repo_text = "[dim italic]Nenhum repositório configurado[/dim italic]\n[yellow]Use: /repo <URL> para clonar um repositório[/yellow]\n\n"

    console.print(
        Panel(
            f"[bold white]Lupus[/bold white] — AI Code Intelligence Agent\n\n"
            f"{repo_text}"
            f"[dim italic]Digite [bold]/comandos[/bold] para ver todas as opções ou [bold]/sair[/bold] para encerrar[/dim italic]",
            border_style="bright_blue",
            title="[bold blue]Lupus[/bold blue]",
            title_align="left",
            padding=(1, 2),
        )
    )
    console.print()


# Nomes de tools → status legível para o usuário
_TOOL_STATUS = {
    "analyze_full_repository": "analisando repositório...",
    "clone_repository": "clonando repositório...",
    "discover_project": "descobrindo tecnologias...",
    "explore_repository": "explorando estrutura...",
    "analyze_code": "analisando código...",
    "generate_documentation": "gerando documentação...",
    "map_code_dependencies": "mapeando dependências...",
    "search_codebase": "buscando no código...",
    "suggest_improvements": "identificando melhorias...",
    "review_architecture": "revisando arquitetura...",
    "read_data_file": "lendo dados...",
    "map_data_lineage": "mapeando linhagem...",
    "get_project_architecture": "analisando arquitetura...",
    "get_data_dictionary": "consultando dicionário...",
    "analyze_dbt_model": "analisando modelo dbt...",
    "analyze_pipeline_config": "analisando pipeline...",
    "get_agent_tools_spec": "inspecionando agent...",
}


def _get_last_ai_text(agent, config: dict, expected_turn: int = 0) -> str | None:
    """Recupera o texto da última mensagem AI do estado do agente.

    Args:
        expected_turn: Número do turn atual (quantidade de mensagens humanas).
                       Se > 0, valida que o estado corresponde ao turn correto
                       para evitar usar resposta de turn anterior (race condition).
    """
    try:
        state = agent.get_state(config)
        messages = state.values.get("messages", [])
        if expected_turn > 0:
            human_count = sum(1 for m in messages if getattr(m, "type", "") == "human")
            if human_count != expected_turn:
                return None  # estado desatualizado
        for msg in reversed(messages):
            if getattr(msg, "type", "") != "ai":
                continue
            text = msg.content
            if isinstance(text, list):
                text = "\n".join(
                    b.get("text", "") for b in text if isinstance(b, dict)
                )
            if isinstance(text, str) and text.strip():
                return text
    except Exception:
        pass
    return None


def _run_with_streaming(agent, user_input: str, config: dict, turn: int = 0) -> tuple[str, list[str]]:
    """Executa o agent com invoke() — fallback seguro para quando streaming falha.

    Retorna (response_text, tool_calls_made).

    Nota: Usa invoke() em vez de stream() porque deepagents 0.4.12/0.5.0a2 têm
    problemas de timeout ao fazer streaming de respostas grandes. invoke() é mais
    confiável e ainda apresenta feedback com "Processando..." enquanto o agente roda.
    """
    tool_calls_made: list[str] = []

    def _make_panel(content: str, status: str = "") -> Panel:
        if status:
            body = Text(status, style="dim italic")
        elif content.strip():
            body = Markdown(content)
        else:
            body = Text("processando...", style="dim italic")
        subtitle = f"[dim]{' → '.join(tool_calls_made)}[/dim]" if tool_calls_made else None
        return Panel(
            body,
            border_style="bright_blue",
            title="[bold blue]Lupus[/bold blue]",
            title_align="left",
            subtitle=subtitle,
            subtitle_align="right",
            padding=(1, 2),
        )

    try:
        displayed = ""
        with Live(
            _make_panel("", "processando..."),
            console=console,
            refresh_per_second=2,
            transient=False,
        ) as live:
            # Invoca o agent com timeout — evita travamento indefinido
            import signal

            def timeout_handler(signum, frame):
                raise TimeoutError("Agent timeout (60s)")

            # Windows não suporta signal.SIGALRM — usar threading em vez disso
            import threading
            result = None
            exception = None

            def invoke_agent():
                nonlocal result, exception
                try:
                    result = agent.invoke(
                        {"messages": [{"role": "user", "content": user_input}]},
                        config=config,
                    )
                except Exception as e:
                    exception = e

            thread = threading.Thread(target=invoke_agent, daemon=True)
            thread.start()
            thread.join(timeout=180)  # 180s timeout — mais tempo para análises pesadas

            if thread.is_alive():
                # Timeout atingido — mensagem clara e não bloqueia mais
                displayed = (
                    "[red]⏱️ Timeout (3 min)[/red] — operação muito lenta\n\n"
                    "[yellow]Tente:[/yellow]\n"
                    "  • Uma pergunta mais simples (ex: 'Qual a arquitetura?')\n"
                    "  • Trocar de repo com [bold]/repo <URL>[/bold]\n"
                    "  • Executar `python scripts/build_rag_index.py` se usar search"
                )
                live.update(_make_panel(displayed))
            elif exception:
                # Erro durante execução
                displayed = f"[red]❌ Erro:[/red] {str(exception)[:100]}"
                live.update(_make_panel(displayed))
            elif result is None:
                # Sem resposta
                displayed = "[red]❌ Sem resposta[/red] — agente não retornou dados.\nTente novamente com uma pergunta diferente."
                live.update(_make_panel(displayed))

            # Extrai ferramentas usadas e última resposta AI (só se não houve timeout/erro)
            if result is not None:
                messages = result.get("messages", [])
                for msg in messages:
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tc in msg.tool_calls:
                            name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                            if name and name not in tool_calls_made:
                                tool_calls_made.append(name)

                # Extrai última resposta AI
                for msg in reversed(messages):
                    if getattr(msg, "type", "") == "ai":
                        content = getattr(msg, "content", "")
                        if isinstance(content, str):
                            displayed = content
                        break

            live.update(_make_panel(displayed))

    except KeyboardInterrupt:
        console.print("\n[dim]Interrompido.[/dim]\n")
    except Exception as e:
        logger.exception("Agent invoke error: %s", e)
        console.print(_make_panel("Erro ao processar sua pergunta.", f"[red]{str(e)[:100]}[/red]"))

    return displayed, tool_calls_made


def chat():
    """Loop principal do chat interativo."""
    _print_banner(ctx_manager.name)

    agent = make_agent()
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}
    skill_mtime = _get_skill_mtime()
    last_repo_version = ctx_manager.repo_change_count
    turn_counter = 0
    _last_turn: dict | None = None  # {question, response, tools_used}

    while True:
        # Hot reload: detecta mudança no SKILL.md e recria o agente
        current_mtime = _get_skill_mtime()
        if current_mtime != skill_mtime and current_mtime != 0.0:
            skill_mtime = current_mtime
            agent = make_agent()
            console.print("[dim yellow]↻ SKILL.md atualizado — agente recarregado[/dim yellow]\n")

        # Hot reload: detecta troca de repositório (via clone_repository) e recria o agente
        if ctx_manager.repo_change_count != last_repo_version:
            last_repo_version = ctx_manager.repo_change_count
            agent = make_agent()
            console.print(
                f"[dim yellow]↻ Repositório alterado para [cyan]{ctx_manager.name}[/cyan] — agente recarregado[/dim yellow]\n"
            )

        try:
            user_input = console.input("[bold blue]Você > [/bold blue]")
        except (KeyboardInterrupt, EOFError):
            break

        if not user_input.strip():
            continue

        cmd = user_input.strip().lower()

        # Comandos especiais
        if cmd in ("sair", "exit", "quit", "/sair", "/exit", "/quit"):
            console.print("\n[bold blue]Até mais.[/bold blue]\n")
            break

        if cmd == "/comandos" or cmd == "/help":
            console.print(Panel(
                "[bold cyan]/repo [URL][/bold cyan]\n"
                "Clona um repositório GitHub para análise\n"
                "[dim]Ex: /repo https://github.com/user/repo[/dim]\n\n"

                "[bold cyan]/status[/bold cyan]\n"
                "Mostra informações do repositório ativo\n"
                "[dim]RAG sync, cache, path, etc[/dim]\n\n"

                "[bold cyan]/export[/bold cyan]\n"
                "Exporta a conversa como arquivo Markdown\n"
                "[dim]Salvo em: ./exports/conversa_TIMESTAMP.md[/dim]\n\n"

                "[bold cyan]/limpar[/bold cyan]\n"
                "Limpa o histórico e inicia nova conversa\n"
                "[dim]Mantém o repositório ativo[/dim]\n\n"

                "[bold cyan]/reportar[/bold cyan]\n"
                "Reporta um problema com a última resposta\n"
                "[dim]Feedback para melhorar o Lupus[/dim]\n\n"

                "[bold cyan]sair[/bold cyan]\n"
                "Encerra a sessão",
                title="📚 Comandos Disponíveis",
                border_style="cyan",
                padding=(1, 2),
            ))
            console.print()
            continue

        if cmd in ("/exportar", "/export"):
            path = _export_conversation(agent, thread_id)
            console.print(f"\n[green]✓ Conversa exportada:[/green] [cyan]{path}[/cyan]\n")
            continue

        if cmd == "/limpar":
            thread_id = str(uuid.uuid4())
            config = {"configurable": {"thread_id": thread_id}}
            turn_counter = 0
            console.clear()
            _print_banner(ctx_manager.name)
            console.print("[dim]Histórico limpo — nova conversa iniciada.[/dim]\n")
            continue

        if cmd.startswith("/repo"):
            # /repo sem args → mostra repositório ativo
            # /repo <url> → clona repositório da URL
            parts = cmd.split(None, 1)
            if len(parts) == 1:
                console.print(f"\n[dim]Repositório ativo: [cyan]{ctx_manager.path}[/cyan][/dim]\n")
            else:
                url = parts[1].strip()
                console.print(f"\n[dim]Clonando {url}...[/dim]\n")
                from tools.github_integration import clone_repository
                try:
                    result_json = clone_repository.invoke({"url": url, "branch": ""})
                    result = json.loads(result_json)

                    if "error" in result:
                        console.print(Panel(
                            f"[red]❌ Erro ao clonar[/red]\n\n{result.get('error')}",
                            title="[bold red]Clone Falhou[/bold red]",
                            border_style="red",
                            padding=(1, 2),
                        ))
                    else:
                        repo_name = result.get('repository', 'repositório')
                        cloned_path = result.get('absolute_path') or result.get('cloned_to')
                        message = result.get('message', '')

                        console.print(Panel(
                            f"[green]✅ {repo_name} clonado com sucesso[/green]\n\n"
                            f"[bold]Localização do arquivo:[/bold]\n"
                            f"[cyan]{cloned_path}[/cyan]\n\n"
                            f"[dim]{message if message else 'PROJECT_PATH atualizado. Pronto para análise.'}[/dim]",
                            title="[bold green]Clone Concluído[/bold green]",
                            border_style="green",
                            padding=(1, 2),
                        ))
                except json.JSONDecodeError as e:
                    console.print(Panel(
                        f"[red]❌ Erro ao processar resposta do clone[/red]\n\n{str(e)}",
                        title="[bold red]Erro Interno[/bold red]",
                        border_style="red",
                        padding=(1, 2),
                    ))
                except Exception as e:
                    console.print(Panel(
                        f"[red]❌ Erro inesperado:[/red]\n{str(e)}",
                        title="[bold red]Erro[/bold red]",
                        border_style="red",
                        padding=(1, 2),
                    ))
            console.print()
            continue

        if cmd == "/status":
            from tools.rag_search import _rag_synced, _indexed_path
            ctx = ctx_manager.context
            cloned_str = (
                datetime.fromtimestamp(ctx.cloned_at).strftime("%H:%M:%S")
                if ctx and ctx.cloned_at else "N/A"
            )
            rag_str = "sincronizado" if _rag_synced else "desatualizado"
            console.print(Panel(
                f"[bold]Repositório ativo:[/bold] {ctx.name if ctx else 'nenhum'}\n"
                f"[bold]Path:[/bold] {ctx.path if ctx else 'N/A'}\n"
                f"[bold]Clonado em:[/bold] {cloned_str}\n"
                f"[bold]RAG indexado:[/bold] {rag_str}\n"
                f"[bold]RAG path:[/bold] {_indexed_path or 'nenhum'}\n"
                f"[bold]Cache version:[/bold] {ctx.cache_version if ctx else 0}\n"
                f"[bold]Turn:[/bold] {turn_counter}",
                title="Status do Lupus",
                border_style="blue",
            ))
            continue

        console.print()
        turn_counter += 1

        # Usa agente em todos os casos — o system prompt em config.py já instrui
        # quando usar tools (com repositório) vs conversação (sem repositório).
        # Uma única superfície de manutenção: agent.invoke() sempre, agente decide.
        response, tool_calls = _run_with_streaming(agent, user_input, config, turn=turn_counter)

        # Pós-processamento de respostas estruturadas (generate_documentation, etc.)
        formatted_doc_response = _format_generated_doc_response(response)
        if formatted_doc_response:
            console.print(Panel(
                formatted_doc_response,
                border_style="green",
                title="[bold green]Documentação Gerada[/bold green]",
                padding=(1, 2),
            ))
            # Se era JSON de geração, não mostra a resposta crua novamente
            response = ""

        # Detecta warnings de RAG desatualizado na resposta (mesmo se oculto em JSON)
        try:
            if "search_codebase" in tool_calls or "RAG" in response or "índice" in response.lower():
                # Tenta parsear como JSON para detectar warnings silenciosos
                if response.strip().startswith("{"):
                    try:
                        resp_json = json.loads(response)
                        if "warning" in resp_json and "RAG" in resp_json.get("warning", ""):
                            # Exibe warning de forma proeminente
                            console.print(Panel(
                                f"[yellow]⚠️  {resp_json['warning']}[/yellow]\n\n"
                                f"[dim]Sugestão:[/dim] Execute `python scripts/build_rag_index.py` para reindexar\n"
                                f"[dim]Enquanto isso:[/dim] Use `/comandos` e tente `/repo <URL>` para outro repositório",
                                title="[bold yellow]Aviso: RAG Desatualizado[/bold yellow]",
                                border_style="yellow",
                                padding=(1, 2),
                            ))
                            # Mostra também a resposta original
                            console.print(f"[dim]Resposta original:[/dim]\n{response}\n")
                    except (json.JSONDecodeError, KeyError, TypeError):
                        pass
        except Exception:
            pass  # Silencioso se houver erro na detecção

        # Salva turno para eventual /reportar
        _last_turn = {
            "question": user_input,
            "response": response,
            "tools_used": tool_calls,
        }

        # Telemetria: mostra tools no console se o streaming não exibiu no painel
        if tool_calls and not response:
            console.print(
                f"[dim]tools chamadas: {', '.join(tool_calls)}[/dim]\n"
            )

        console.print()


if __name__ == "__main__":
    chat()
