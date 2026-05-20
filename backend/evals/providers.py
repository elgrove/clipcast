from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass

from app.models import PRESET_MODELS, AIModel, Provider
from app.services.providers import AIProviderBase, GeminiProvider


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    api_key_env: str
    factory: Callable[[str, str], AIProviderBase]


def _gemini_factory(model_name: str, api_key: str) -> AIProviderBase:
    model_config = AIModel(
        name=model_name,
        provider=Provider.GEMINI.value,
        is_preset=False,
    )
    return GeminiProvider(api_key=api_key, model_config=model_config)


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
      - ``model_name`` alone — provider is inferred from PRESET_MODELS

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
        preset = PRESET_MODELS.get(spec)
        if not preset:
            raise ProviderError(
                f"Cannot infer provider from {spec!r}. Use 'provider:model' (e.g. 'gemini:{spec}')."
            )
        provider = preset["provider"].value
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
