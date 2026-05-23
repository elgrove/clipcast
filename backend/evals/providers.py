from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from app.models import AIModel, AIProvider, Provider
from app.services.openrouter_models import fetch_context_length
from app.services.providers import (
    AIProviderBase,
    GeminiProvider,
    OpenAICompatibleProvider,
    OpenAIProvider,
    OpenRouterProvider,
)

# Same defaults the app uses for context-window auto-derivation. Kept in sync
# with backend/app/routers/config.py:DEFAULT_CONTEXT_WINDOWS — if you change
# one, change both.
GEMINI_CONTEXT_WINDOW = 1_048_576
OPENAI_CONTEXT_WINDOW = 262_144
OPENAI_COMPATIBLE_CONTEXT_WINDOW = 131_072

# Process-local memo so a bake-off across N OpenRouter models hits the catalogue
# endpoint once instead of N times.
_openrouter_context_cache: dict[str, int] = {}


def _openrouter_context(model_name: str, api_key: str) -> int:
    if model_name in _openrouter_context_cache:
        return _openrouter_context_cache[model_name]
    value = fetch_context_length(model_name, api_key) or OPENAI_COMPATIBLE_CONTEXT_WINDOW
    _openrouter_context_cache[model_name] = value
    return value

# Bare-name → provider shortcut for the evals harness. Add entries here when a
# new model gets common enough that typing the provider prefix is tedious.
KNOWN_BARE_MODELS: dict[str, Provider] = {
    "gemini-2.5-flash": Provider.GEMINI,
    "gemini-2.5-flash-lite": Provider.GEMINI,
}


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    api_key_env: str
    factory: Callable[[str, str], AIProviderBase]


# Pricing table for cost reporting. Values are cents per 1M tokens for text
# input/output (matching app/services/providers.py:calculate_cost which divides
# by 100). Update whenever Google adjusts list prices.
# Source: https://ai.google.dev/pricing (verified 2026-05-22).
GEMINI_PRICING: dict[str, tuple[int, int]] = {
    "gemini-2.5-flash": (30, 250),  # $0.30 in / $2.50 out per 1M tokens
    "gemini-2.5-flash-lite": (10, 40),  # $0.10 in / $0.40 out per 1M tokens
    "gemini-3.5-flash": (150, 900),  # $1.50 in / $9.00 out per 1M tokens
    "gemini-3-flash-preview": (50, 300),  # $0.50 in / $3.00 out per 1M tokens
}

# OpenAI list pricing (cents per 1M tokens). Source: https://openai.com/api/pricing
# (verified 2026-05-22). Only needed as a fallback — OpenAI returns token usage
# but not cost, so without an entry here `calculate_cost` returns 0.
OPENAI_PRICING: dict[str, tuple[int, int]] = {
    "gpt-5": (125, 1000),
    "gpt-5-mini": (25, 200),
    "gpt-5-nano": (5, 40),
}


def _gemini_factory(model_name: str, api_key: str) -> AIProviderBase:
    input_price, output_price = GEMINI_PRICING.get(model_name, (0, 0))
    provider_config = AIProvider(
        kind=Provider.GEMINI.value,
        name="Gemini",
        api_key=api_key,
    )
    model_config = AIModel(
        provider_id=provider_config.id,
        name=model_name,
        input_price=input_price,
        output_price=output_price,
        context_window=GEMINI_CONTEXT_WINDOW,
    )
    model_config.provider = provider_config
    return GeminiProvider(provider_config=provider_config, model_config=model_config)


def _openai_factory(model_name: str, api_key: str) -> AIProviderBase:
    input_price, output_price = OPENAI_PRICING.get(model_name, (0, 0))
    provider_config = AIProvider(
        kind=Provider.OPENAI.value,
        name="OpenAI",
        api_key=api_key,
    )
    model_config = AIModel(
        provider_id=provider_config.id,
        name=model_name,
        input_price=input_price,
        output_price=output_price,
        context_window=OPENAI_CONTEXT_WINDOW,
    )
    model_config.provider = provider_config
    return OpenAIProvider(provider_config=provider_config, model_config=model_config)


def _openrouter_factory(model_name: str, api_key: str) -> AIProviderBase:
    # OpenRouter returns the authoritative dollar cost in `usage.cost` on every
    # response (see OpenRouterProvider._extract_cost), so we don't need a local
    # pricing table — leave list prices at zero and rely on response-side cost.
    # Context window is fetched live from OpenRouter's /api/v1/models, cached
    # per-process so a multi-model bake-off only hits the catalogue once.
    provider_config = AIProvider(
        kind=Provider.OPENROUTER.value,
        name="OpenRouter",
        api_key=api_key,
    )
    model_config = AIModel(
        provider_id=provider_config.id,
        name=model_name,
        input_price=0,
        output_price=0,
        context_window=_openrouter_context(model_name, api_key),
    )
    model_config.provider = provider_config
    return OpenRouterProvider(provider_config=provider_config, model_config=model_config)


def _openai_compatible_factory(model_name: str, api_key: str) -> AIProviderBase:
    # Generic OpenAI-compatible endpoints need a base URL — pulled from the
    # OPENAI_COMPATIBLE_BASE_URL env var so a single registry entry can target
    # any vendor. Pricing must be set by the caller; left at zero by default.
    base_url = os.environ.get("OPENAI_COMPATIBLE_BASE_URL", "")
    if not base_url:
        raise ProviderError(
            "OPENAI_COMPATIBLE_BASE_URL is not set. The 'openai-compatible' eval "
            "provider needs a base URL (e.g. http://localhost:8000/v1)."
        )
    provider_config = AIProvider(
        kind=Provider.OPENAI_COMPATIBLE.value,
        name="OpenAI-compatible",
        api_key=api_key,
        base_url=base_url,
    )
    model_config = AIModel(
        provider_id=provider_config.id,
        name=model_name,
        input_price=0,
        output_price=0,
        context_window=OPENAI_COMPATIBLE_CONTEXT_WINDOW,
    )
    model_config.provider = provider_config
    return OpenAICompatibleProvider(
        provider_config=provider_config, model_config=model_config
    )


REGISTRY: dict[str, ProviderSpec] = {
    "gemini": ProviderSpec(
        name="gemini",
        api_key_env="GEMINI_API_KEY",
        factory=_gemini_factory,
    ),
    "openai": ProviderSpec(
        name="openai",
        api_key_env="OPENAI_API_KEY",
        factory=_openai_factory,
    ),
    "openrouter": ProviderSpec(
        name="openrouter",
        api_key_env="OPENROUTER_API_KEY",
        factory=_openrouter_factory,
    ),
    "openai-compatible": ProviderSpec(
        name="openai-compatible",
        api_key_env="OPENAI_COMPATIBLE_API_KEY",
        factory=_openai_compatible_factory,
    ),
}


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider}:{self.model}"


class ProviderError(RuntimeError):
    pass


def parse_model_spec(spec: str) -> ModelSpec:
    """Parse a model identifier.

    Accepts either:
      - ``provider:model_name`` (explicit) — e.g. ``gemini:gemini-2.5-flash``
      - ``model_name`` alone — provider inferred from KNOWN_BARE_MODELS

    Provider-prefixed specs may contain further colons or slashes in the model
    portion (e.g. ``openrouter:meta-llama/llama-4-scout``) — only the first
    ``:`` is treated as the provider separator.

    Raises ProviderError if the provider can't be determined or isn't registered.
    """
    spec = spec.strip()
    if not spec:
        raise ProviderError("Empty model spec")

    if ":" in spec:
        provider, _, model = spec.partition(":")
        provider = provider.strip()
        model = model.strip()
        if not provider or not model:
            raise ProviderError(f"Invalid model spec: {spec!r}")
    else:
        known = KNOWN_BARE_MODELS.get(spec)
        if not known:
            raise ProviderError(
                f"Cannot infer provider from {spec!r}. Use 'provider:model' (e.g. 'gemini:{spec}')."
            )
        provider = known.value
        model = spec

    if provider not in REGISTRY:
        known = ", ".join(sorted(REGISTRY)) or "(none)"
        raise ProviderError(f"Unknown provider {provider!r}. Registered: {known}")

    return ModelSpec(provider=provider, model=model)


def build_provider(spec: ModelSpec) -> AIProviderBase:
    entry = REGISTRY[spec.provider]
    api_key = os.environ.get(entry.api_key_env, "")
    if not api_key:
        raise ProviderError(
            f"{entry.api_key_env} is not set. Add it to backend/evals/.env.evals "
            f"or export it in your shell."
        )
    return entry.factory(spec.model, api_key)
