"""Fábrica de LLM para o Lupus.

Seleciona e configura o provedor de LLM com base em variáveis de ambiente,
mantendo o restante do código desacoplado de qualquer provider específico.

Variáveis de ambiente:
    LLM_PROVIDER    : gemini | claude | openai | openai_compat  (padrão: gemini)
    LLM_MODEL       : nome do modelo (padrão varia por provider — ver abaixo)
    LLM_BASE_URL    : apenas para openai_compat (ex: http://localhost:11434/v1)
    LLM_TEMPERATURE : temperatura do modelo (padrão: 0)

Defaults por provider:
    gemini        → gemini-2.5-flash   (requer GOOGLE_API_KEY)
    claude        → claude-haiku-4-5-20251001  (requer ANTHROPIC_API_KEY)
    openai        → gpt-4o-mini        (requer OPENAI_API_KEY)
    openai_compat → depende do servidor (requer LLM_BASE_URL + OPENAI_API_KEY ou sem key)

Exemplos de uso no .env:
    # Gemini (padrão — mantém comportamento atual)
    LLM_PROVIDER=gemini
    LLM_MODEL=gemini-2.5-flash
    GOOGLE_API_KEY=...

    # Claude (provider nativo do deepagents)
    LLM_PROVIDER=claude
    LLM_MODEL=claude-haiku-4-5-20251001
    ANTHROPIC_API_KEY=...

    # OpenAI
    LLM_PROVIDER=openai
    LLM_MODEL=gpt-4o-mini
    OPENAI_API_KEY=...

    # Ollama local (OpenAI-compat)
    LLM_PROVIDER=openai_compat
    LLM_MODEL=llama3.2
    LLM_BASE_URL=http://localhost:11434/v1
"""

import logging
import os

logger = logging.getLogger(__name__)

# Modelos padrão por provider
_DEFAULTS = {
    "gemini": "gemini-2.5-flash",
    "claude": "claude-haiku-4-5-20251001",
    "openai": "gpt-4o-mini",
    "openai_compat": "llama3.2",
}

_VALID_PROVIDERS = set(_DEFAULTS.keys())


def build_llm():
    """Constrói e retorna a instância de LLM configurada via variáveis de ambiente.

    Returns:
        BaseChatModel: Instância de LLM compatível com LangChain.

    Raises:
        ValueError: Se o provider for inválido ou a API key necessária estiver ausente.
        ImportError: Se a dependência do provider selecionado não estiver instalada.
    """
    provider = os.getenv("LLM_PROVIDER", "gemini").lower().strip()
    model = os.getenv("LLM_MODEL", "").strip() or _DEFAULTS.get(provider, "")
    temperature = _parse_temperature(os.getenv("LLM_TEMPERATURE", "0"))
    base_url = os.getenv("LLM_BASE_URL", "").strip()

    if provider not in _VALID_PROVIDERS:
        raise ValueError(
            f"LLM_PROVIDER='{provider}' inválido. "
            f"Opções: {', '.join(sorted(_VALID_PROVIDERS))}. "
            "Configure no arquivo .env ou como variável de ambiente."
        )

    logger.debug("Inicializando LLM: provider=%s model=%s temperature=%s", provider, model, temperature)

    if provider == "gemini":
        return _build_gemini(model, temperature)
    elif provider == "claude":
        return _build_claude(model, temperature)
    elif provider == "openai":
        return _build_openai(model, temperature)
    elif provider == "openai_compat":
        return _build_openai_compat(model, temperature, base_url)


# ---------------------------------------------------------------------------
# Builders por provider
# ---------------------------------------------------------------------------

def _build_gemini(model: str, temperature: float):
    """Instancia ChatGoogleGenerativeAI."""
    _require_key("GOOGLE_API_KEY", "gemini", "https://aistudio.google.com/app/apikey")
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        raise ImportError(
            "langchain-google-genai não está instalado. "
            "Execute: pip install langchain-google-genai"
        )
    return ChatGoogleGenerativeAI(model=model, temperature=temperature)


def _build_claude(model: str, temperature: float):
    """Instancia ChatAnthropic."""
    _require_key("ANTHROPIC_API_KEY", "claude", "https://console.anthropic.com/settings/keys")
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        raise ImportError(
            "langchain-anthropic não está instalado. "
            "Execute: pip install langchain-anthropic"
        )
    return ChatAnthropic(model=model, temperature=temperature)


def _build_openai(model: str, temperature: float):
    """Instancia ChatOpenAI com API OpenAI."""
    _require_key("OPENAI_API_KEY", "openai", "https://platform.openai.com/api-keys")
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise ImportError(
            "langchain-openai não está instalado. "
            "Execute: pip install langchain-openai"
        )
    return ChatOpenAI(model=model, temperature=temperature)


def _build_openai_compat(model: str, temperature: float, base_url: str):
    """Instancia ChatOpenAI apontando para servidor OpenAI-compatível (Ollama, OpenRouter, etc.)."""
    if not base_url:
        raise ValueError(
            "LLM_PROVIDER=openai_compat requer LLM_BASE_URL configurado. "
            "Exemplos:\n"
            "  Ollama:     LLM_BASE_URL=http://localhost:11434/v1\n"
            "  OpenRouter: LLM_BASE_URL=https://openrouter.ai/api/v1"
        )
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        raise ImportError(
            "langchain-openai não está instalado. "
            "Execute: pip install langchain-openai"
        )

    api_key = os.getenv("OPENAI_API_KEY", "ollama")  # Ollama não exige key real
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        base_url=base_url,
        api_key=api_key,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_key(env_var: str, provider: str, url: str) -> None:
    """Valida que a API key necessária está definida."""
    if not os.getenv(env_var):
        raise ValueError(
            f"{env_var} não definida. "
            f"Necessária para LLM_PROVIDER={provider}. "
            f"Obtenha em: {url} — "
            "Configure no arquivo .env ou como variável de ambiente."
        )


def _parse_temperature(value: str) -> float:
    """Converte LLM_TEMPERATURE para float com fallback seguro."""
    try:
        temp = float(value)
        if not 0.0 <= temp <= 2.0:
            logger.warning(
                "LLM_TEMPERATURE=%.2f fora do intervalo esperado [0, 2]. Usando 0.", temp
            )
            return 0.0
        return temp
    except (ValueError, TypeError):
        logger.warning("LLM_TEMPERATURE='%s' inválido. Usando padrão: 0.", value)
        return 0.0
