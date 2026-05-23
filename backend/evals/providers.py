from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from app.models import AIModel, AIProvider, Provider
from app.services.providers import AIProviderBase, GeminiProvider

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
    )
    model_config.provider = provider_config
    return GeminiProvider(provider_config=provider_config, model_config=model_config)


REGISTRY: dict[str, ProviderSpec] = {
    "gemini": ProviderSpec(
        name="gemini",
        api_key_env="GEMINI_API_KEY",
        factory=_gemini_factory,
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
            f"{entry.api_key_env} is not set. Add it to backend/.env or export it in your shell."
        )
    return entry.factory(spec.model, api_key)
