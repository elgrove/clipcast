import pytest

from app.services.providers import GeminiProvider
from evals.providers import (
    ModelSpec,
    ProviderError,
    build_provider,
    parse_model_spec,
)

# ── parse_model_spec ─────────────────────────────────────────────────────────


def test_parse_model_spec_explicit():
    spec = parse_model_spec("gemini:gemini-2.5-flash")
    assert spec == ModelSpec(provider="gemini", model="gemini-2.5-flash")


def test_parse_model_spec_bare_known_model():
    # KNOWN_BARE_MODELS contains gemini-2.5-flash with provider Gemini
    spec = parse_model_spec("gemini-2.5-flash")
    assert spec == ModelSpec(provider="gemini", model="gemini-2.5-flash")


def test_parse_model_spec_custom_model_under_known_provider():
    spec = parse_model_spec("gemini:gemini-experimental-1234")
    assert spec.provider == "gemini"
    assert spec.model == "gemini-experimental-1234"


def test_parse_model_spec_unknown_provider():
    with pytest.raises(ProviderError, match="Unknown provider"):
        parse_model_spec("anthropic:claude-3.5-sonnet")


def test_parse_model_spec_unknown_bare_model():
    with pytest.raises(ProviderError, match="Cannot infer provider"):
        parse_model_spec("some-totally-unknown-model")


def test_parse_model_spec_empty():
    with pytest.raises(ProviderError, match="Empty"):
        parse_model_spec("   ")


def test_parse_model_spec_malformed():
    with pytest.raises(ProviderError, match="Invalid"):
        parse_model_spec("gemini:")
    with pytest.raises(ProviderError, match="Invalid"):
        parse_model_spec(":gemini-2.5-flash")


def test_model_spec_label():
    spec = ModelSpec(provider="gemini", model="gemini-2.5-flash")
    assert spec.label == "gemini:gemini-2.5-flash"


# ── build_provider ───────────────────────────────────────────────────────────


def test_build_provider_requires_api_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    spec = ModelSpec(provider="gemini", model="gemini-2.5-flash")
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        build_provider(spec)


def test_build_provider_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    spec = ModelSpec(provider="gemini", model="gemini-2.5-flash")
    provider = build_provider(spec)
    assert isinstance(provider, GeminiProvider)
    assert provider.api_key == "test-key"
    assert provider.model_config.name == "gemini-2.5-flash"
