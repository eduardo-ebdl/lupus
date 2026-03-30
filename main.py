"""Lupus — AI Code Intelligence Agent (CLI Chat)"""

import logging
import os
import time
import uuid
from datetime import datetime

# Suprime warnings de carregamento de pesos do HuggingFace/sentence-transformers
logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

from config import make_agent
from core.context_manager import ctx_manager
from feedback.feedback_store import log_report, search_similar, build_few_shot_prefix, generate_suggested_fix

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


def _print_banner(repo_name: str):
    """Exibe banner de boas-vindas com o repositório ativo."""
    console.print()
    console.print(
        Panel(
            f"[bold white]Lupus[/bold white] — AI Code Intelligence Agent\n"
            f"[dim]Repositório: [cyan]{repo_name}[/cyan][/dim]\n\n"
            f"[dim italic]Comandos: /export · /limpar · /repo · /status · /reportar · sair[/dim italic]",
            border_style="bright_yellow",
            title="[bold yellow]Lupus[/bold yellow]",
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
    """Executa o agent com streaming de tokens e coleta telemetria de tools.

    Retorna (response_text, tool_calls_made).

    Buffer inteligente: texto gerado antes de um tool call (anúncios como
    "Vou analisar...") é descartado. Texto após tool calls é a resposta real.
    Se 3s passam sem tool call, o buffer é tratado como resposta real (flush).
    """
    displayed = ""       # texto já renderizado no painel
    pre_buffer = ""      # texto pré-tool-call (pode ser descartado)
    pre_buffer_flushed = False  # True após flush — renderização direta
    pre_buffer_start: float | None = None
    tool_calls_made: list[str] = []
    status_text = "pensando..."

    _BUFFER_TIMEOUT = 3.0  # segundos sem tool call → flush buffer

    def _make_panel(content: str) -> Panel:
        body = Markdown(content) if content.strip() else Text(status_text, style="dim italic")
        subtitle = f"[dim]{' → '.join(tool_calls_made)}[/dim]" if tool_calls_made else None
        return Panel(
            body,
            border_style="bright_yellow",
            title="[bold yellow]Lupus[/bold yellow]",
            title_align="left",
            subtitle=subtitle,
            subtitle_align="right",
            padding=(1, 2),
        )

    def _extract_text(chunk) -> str:
        """Extrai texto de um chunk de streaming."""
        raw = chunk.content
        if isinstance(raw, list):
            return "".join(b.get("text", "") for b in raw if isinstance(b, dict))
        elif isinstance(raw, str):
            return raw
        return ""

    try:
        with Live(
            _make_panel(""),
            console=console,
            refresh_per_second=15,
            transient=False,
        ) as live:
            for chunk, metadata in agent.stream(
                {"messages": [{"role": "user", "content": user_input}]},
                config=config,
                stream_mode="messages",
            ):
                # Detecta tool calls → descarta buffer de anúncio
                if hasattr(chunk, "tool_calls") and chunk.tool_calls:
                    for tc in chunk.tool_calls:
                        name = tc.get("name", "")
                        if name and name not in tool_calls_made:
                            tool_calls_made.append(name)
                            status_text = _TOOL_STATUS.get(name, f"executando {name}...")
                    if not pre_buffer_flushed:
                        pre_buffer = ""  # descarta anúncio
                        pre_buffer_flushed = True  # texto pós-tool é resposta real
                    live.update(_make_panel(displayed))
                    continue

                # Acumula tokens de texto
                if hasattr(chunk, "content") and chunk.content:
                    chunk_type = getattr(chunk, "type", "")
                    if chunk_type in ("tool", "ToolMessage", "ToolMessageChunk",
                                      "human", "HumanMessage", "HumanMessageChunk"):
                        continue
                    if hasattr(chunk, "tool_calls") and chunk.tool_calls:
                        continue

                    text = _extract_text(chunk)
                    if not text:
                        continue

                    if not pre_buffer_flushed:
                        # Ainda acumulando no buffer pré-tool
                        pre_buffer += text
                        if pre_buffer_start is None:
                            pre_buffer_start = time.time()

                        # Timeout: sem tool call → é resposta real, flush
                        if pre_buffer_start and (time.time() - pre_buffer_start) >= _BUFFER_TIMEOUT:
                            displayed += pre_buffer
                            pre_buffer = ""
                            pre_buffer_flushed = True
                            live.update(_make_panel(displayed))
                        else:
                            live.update(_make_panel(displayed))
                    else:
                        # Buffer já flushed — renderizar direto
                        displayed += text
                        live.update(_make_panel(displayed))

            # Stream terminou — flush qualquer buffer restante
            if pre_buffer and not pre_buffer_flushed:
                displayed += pre_buffer

            # Safety net: verifica estado para resposta definitiva
            state_text = _get_last_ai_text(agent, config, expected_turn=turn)
            if state_text and len(state_text.strip()) > len(displayed.strip()):
                displayed = state_text
            live.update(_make_panel(displayed))

    except KeyboardInterrupt:
        console.print("\n[dim]Interrompido.[/dim]\n")
    except Exception:
        # Streaming falhou — recupera resposta do estado
        state_text = _get_last_ai_text(agent, config, expected_turn=turn)
        if state_text:
            displayed = state_text
            console.print(_make_panel(displayed))

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
            user_input = console.input("[bold yellow]Você > [/bold yellow]")
        except (KeyboardInterrupt, EOFError):
            break

        if not user_input.strip():
            continue

        cmd = user_input.strip().lower()

        # Comandos especiais
        if cmd in ("sair", "exit", "quit", "/sair", "/exit", "/quit"):
            console.print("\n[bold yellow]Até mais.[/bold yellow]\n")
            break

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

        if cmd == "/repo":
            console.print(f"\n[dim]Repositório ativo: [cyan]{ctx_manager.path}[/cyan][/dim]\n")
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

        if cmd.startswith("/reportar"):
            if _last_turn is None:
                console.print("[dim]Nenhuma resposta anterior para reportar.[/dim]\n")
                continue
            comment = user_input.strip()[len("/reportar"):].strip() or None
            with console.status("[dim]analisando...[/dim]", spinner="dots"):
                suggested_fix = generate_suggested_fix(
                    question=_last_turn["question"],
                    response=_last_turn["response"],
                    comment=comment,
                )
            log_report(
                question=_last_turn["question"],
                response=_last_turn["response"],
                tools_used=_last_turn["tools_used"],
                thread_id=thread_id,
                comment=comment,
                suggested_fix=suggested_fix,
            )
            console.print("[green]✓ Report registrado.[/green]\n")
            continue

        # Few-shot RAG: injeta contexto de reports similares antes de enviar ao agente
        similar = search_similar(user_input)
        prefix = build_few_shot_prefix(similar)
        augmented_input = prefix + user_input if prefix else user_input

        console.print()
        turn_counter += 1
        response, tool_calls = _run_with_streaming(agent, augmented_input, config, turn=turn_counter)

        console.print("[dim]  Resposta incorreta? /reportar[/dim]")

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
