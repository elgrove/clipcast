"""Tests for the OpenAI-compatible provider base class, OpenAIProvider,
OpenRouterProvider, and the get_ai_provider() selector wiring."""

from types import SimpleNamespace

import pytest

from app.models import (
    AIModel,
    AIProvider,
    AnalysisReport,
    AppConfig,
)
from app.services.prompts import ADS_CONTEXT_FULL_EPISODE
from app.services.providers import (
    ANALYSIS_TIMEOUT,
    AdBreaksResponse,
    OpenAICompatibleProvider,
    OpenAIProvider,
    OpenRouterProvider,
    Transcription,
    _AdBreakOut,
    _AdvertOut,
    get_ai_provider,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _openrouter_pair(api_key: str = "sk-or-v1-test") -> tuple[AIProvider, AIModel]:
    provider = AIProvider(kind="openrouter", name="OpenRouter", api_key=api_key)
    model = AIModel(
        provider_id=provider.id,
        name="anthropic/claude-sonnet-4",
        input_price=0.0,
        output_price=0.0,
        supports_analysis=True,
    )
    model.provider = provider
    return provider, model


def _openai_pair(
    name: str = "gpt-4o-mini",
    api_key: str = "sk-test",
    input_price: float = 0.0,
    output_price: float = 0.0,
    supports_transcription: bool = False,
    supports_analysis: bool = True,
) -> tuple[AIProvider, AIModel]:
    provider = AIProvider(kind="openai", name="OpenAI", api_key=api_key)
    model = AIModel(
        provider_id=provider.id,
        name=name,
        input_price=input_price,
        output_price=output_price,
        supports_transcription=supports_transcription,
        supports_analysis=supports_analysis,
    )
    model.provider = provider
    return provider, model


def _fake_completion(*, cost: float | None = 0.0123, parsed_breaks=None):
    parsed = AdBreaksResponse(
        breaks=parsed_breaks
        or [
            _AdBreakOut(
                start_time="00:00:10.000",
                end_time="00:00:25.000",
                adverts=[
                    _AdvertOut(
                        start_time="00:00:10.000",
                        end_time="00:00:25.000",
                        advert_for="Squarespace",
                    )
                ],
            ),
        ]
    )
    usage_kwargs = {"prompt_tokens": 1200, "completion_tokens": 80}
    if cost is not None:
        usage_kwargs["cost"] = cost
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(parsed=parsed, content=None))],
        usage=SimpleNamespace(**usage_kwargs),
    )


class _FakeOpenAI:
    """Minimal stand-in for the openai.OpenAI client, capturing the kwargs
    passed to chat.completions.parse and returning a canned completion."""

    last_init_kwargs: dict | None = None
    last_call_kwargs: dict | None = None

    def __init__(self, completion):
        self._completion = completion

        parser = SimpleNamespace(parse=self._parse)
        chat = SimpleNamespace(completions=parser)
        self.beta = SimpleNamespace(chat=chat)

    def _parse(self, **kwargs):
        type(self).last_call_kwargs = kwargs
        return self._completion


def _patch_openai(monkeypatch, completion):
    def _factory(**init_kwargs):
        _FakeOpenAI.last_init_kwargs = init_kwargs
        return _FakeOpenAI(completion)

    monkeypatch.setattr("app.services.providers.OpenAI", _factory)


# ── Selector validation ──────────────────────────────────────────────────────


def test_get_ai_provider_openrouter_requires_api_key(session):
    """Provider-level api_key is required for OpenRouter."""
    provider_row, model = _openrouter_pair(api_key="")
    session.add(provider_row)
    session.add(model)
    session.commit()
    session.refresh(model)

    config = session.get(AppConfig, "config")
    config.analysis_model_id = model.id
    session.add(config)
    session.commit()
    session.refresh(config)

    with pytest.raises(ValueError, match="No API key configured"):
        get_ai_provider("analysis", config)


def test_get_ai_provider_returns_openrouter_provider(session):
    provider_row, model = _openrouter_pair()
    session.add(provider_row)
    session.add(model)
    session.commit()
    session.refresh(model)

    config = session.get(AppConfig, "config")
    config.analysis_model_id = model.id
    session.add(config)
    session.commit()
    session.refresh(config)

    provider = get_ai_provider("analysis", config)
    assert isinstance(provider, OpenRouterProvider)
    assert provider.provider_config.api_key == "sk-or-v1-test"
    assert provider.model_config.name == "anthropic/claude-sonnet-4"


# ── OpenRouterProvider analyse_ads ───────────────────────────────────────────


def test_openrouter_provider_analyse_ads_happy_path(monkeypatch):
    _patch_openai(monkeypatch, _fake_completion(cost=0.0042))

    provider_row, model = _openrouter_pair()
    provider = OpenRouterProvider(provider_config=provider_row, model_config=model)
    transcription = Transcription(segments=[])
    report = AnalysisReport()

    result = provider.analyse_ads(transcription, ADS_CONTEXT_FULL_EPISODE, report=report)

    assert len(result) == 1
    assert result[0].adverts[0].advert_for == "Squarespace"
    assert report.input_tokens == 1200
    assert report.output_tokens == 80
    assert report.cost_usd == 0.0042

    # Client was pointed at OpenRouter; no leaderboard headers attached
    assert _FakeOpenAI.last_init_kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert _FakeOpenAI.last_init_kwargs["api_key"] == "sk-or-v1-test"
    call = _FakeOpenAI.last_call_kwargs
    assert call["model"] == "anthropic/claude-sonnet-4"
    assert call["response_format"] is AdBreaksResponse
    assert call["timeout"] == ANALYSIS_TIMEOUT
    assert call["extra_headers"] is None
    assert call["extra_body"] == {"usage": {"include": True}}


def test_openrouter_provider_cost_falls_back_when_response_omits_cost(monkeypatch):
    _patch_openai(monkeypatch, _fake_completion(cost=None))

    provider_row, model = _openrouter_pair()
    model.input_price = 300  # arbitrary, just to prove calculate_cost ran
    model.output_price = 1500
    provider = OpenRouterProvider(provider_config=provider_row, model_config=model)
    report = AnalysisReport()

    provider.analyse_ads(Transcription(segments=[]), ADS_CONTEXT_FULL_EPISODE, report=report)

    # Fell back to calculate_cost() with the model's per-million prices
    expected = provider.calculate_cost(1200, 80, model)
    assert report.cost_usd == expected
    assert expected > 0


def test_openrouter_provider_appends_custom_instructions(monkeypatch):
    _patch_openai(monkeypatch, _fake_completion())

    provider_row, model = _openrouter_pair()
    provider = OpenRouterProvider(provider_config=provider_row, model_config=model)
    provider.analyse_ads(
        Transcription(segments=[]),
        ADS_CONTEXT_FULL_EPISODE,
        report=AnalysisReport(),
        custom_instructions="Ignore mentions of Patreon.",
    )

    prompt = _FakeOpenAI.last_call_kwargs["messages"][0]["content"]
    assert "Additional instructions:" in prompt
    assert "Ignore mentions of Patreon." in prompt


# ── OpenAIProvider ───────────────────────────────────────────────────────────


def test_get_ai_provider_returns_openai_provider(session):
    provider_row, model = _openai_pair()
    session.add(provider_row)
    session.add(model)
    session.commit()
    session.refresh(model)

    config = session.get(AppConfig, "config")
    config.analysis_model_id = model.id
    session.add(config)
    session.commit()
    session.refresh(config)

    provider = get_ai_provider("analysis", config)
    assert isinstance(provider, OpenAIProvider)
    assert provider.provider_config.api_key == "sk-test"
    assert provider.model_config.name == "gpt-4o-mini"


def test_get_ai_provider_openai_requires_api_key(session):
    provider_row, model = _openai_pair(api_key="")
    session.add(provider_row)
    session.add(model)
    session.commit()
    session.refresh(model)

    config = session.get(AppConfig, "config")
    config.analysis_model_id = model.id
    session.add(config)
    session.commit()
    session.refresh(config)

    with pytest.raises(ValueError, match="No API key configured"):
        get_ai_provider("analysis", config)


def test_openai_provider_analyse_ads_happy_path(monkeypatch):
    # OpenAI's response has no `cost` field — base class falls back to calculate_cost
    _patch_openai(monkeypatch, _fake_completion(cost=None))

    provider_row, model = _openai_pair(input_price=15.0, output_price=60.0)
    provider = OpenAIProvider(provider_config=provider_row, model_config=model)
    report = AnalysisReport()

    result = provider.analyse_ads(
        Transcription(segments=[]), ADS_CONTEXT_FULL_EPISODE, report=report
    )

    assert len(result) == 1
    assert report.input_tokens == 1200
    assert report.output_tokens == 80
    expected = provider.calculate_cost(1200, 80, model)
    assert report.cost_usd == expected

    assert _FakeOpenAI.last_init_kwargs["base_url"] == "https://api.openai.com/v1"
    assert _FakeOpenAI.last_init_kwargs["api_key"] == "sk-test"
    call = _FakeOpenAI.last_call_kwargs
    assert call["model"] == "gpt-4o-mini"
    assert call["response_format"] is AdBreaksResponse
    assert call["timeout"] == ANALYSIS_TIMEOUT
    # No OpenRouter-only extras leak in
    assert call["extra_headers"] is None
    assert "extra_body" not in call


# ── Shared base class reuse ──────────────────────────────────────────────────


def test_openai_compatible_base_is_reusable_without_openrouter_overrides(monkeypatch):
    """A thin subclass with just a base_url should work end-to-end. This locks
    in that the base is genuinely reusable for future OpenAI / Groq / vLLM /
    etc. providers, and proves OpenRouter's cost extraction is the only
    OpenRouter-specific bit — not baked into the base."""

    _patch_openai(monkeypatch, _fake_completion(cost=99.99))  # ignored by base

    class _MyProvider(OpenAICompatibleProvider):
        base_url = "https://api.example.test/v1"

    provider_row = AIProvider(kind="openrouter", name="Example", api_key="example-key")
    model = AIModel(
        provider_id=provider_row.id,
        name="example/foo",
        input_price=0,
        output_price=0,
    )
    model.provider = provider_row
    provider = _MyProvider(provider_config=provider_row, model_config=model)
    report = AnalysisReport()

    result = provider.analyse_ads(
        Transcription(segments=[]), ADS_CONTEXT_FULL_EPISODE, report=report
    )

    assert len(result) == 1
    assert report.input_tokens == 1200
    assert report.output_tokens == 80
    # Base _extract_cost returns None → falls back to calculate_cost (0 here)
    assert report.cost_usd == 0
    assert _FakeOpenAI.last_init_kwargs["base_url"] == "https://api.example.test/v1"
    # No extra_body unless subclass opts in
    assert "extra_body" not in _FakeOpenAI.last_call_kwargs


# ── parse_refinement_offset ──────────────────────────────────────────────────


def test_parse_refinement_offset_bare_int():
    from app.services.providers import parse_refinement_offset

    assert parse_refinement_offset("1234") == 1234
    assert parse_refinement_offset(" 1234 ") == 1234
    assert parse_refinement_offset("0") == 0


def test_parse_refinement_offset_json_shape():
    from app.services.providers import parse_refinement_offset

    assert parse_refinement_offset('{"offset_ms": 1234}') == 1234
    assert parse_refinement_offset('{"offset_ms": "2345"}') == 2345


def test_parse_refinement_offset_code_fenced():
    from app.services.providers import parse_refinement_offset

    assert parse_refinement_offset("```\n1234\n```") == 1234
    assert parse_refinement_offset('```json\n{"offset_ms": 1234}\n```') == 1234


def test_parse_refinement_offset_negative_returns_none():
    from app.services.providers import parse_refinement_offset

    assert parse_refinement_offset("-1") is None
    assert parse_refinement_offset("-100") is None


def test_parse_refinement_offset_unparseable_returns_none():
    from app.services.providers import parse_refinement_offset

    assert parse_refinement_offset(None) is None
    assert parse_refinement_offset("") is None
    assert parse_refinement_offset("   ") is None
    assert parse_refinement_offset("I cannot determine the transition") is None
    assert parse_refinement_offset('{"something_else": 5}') is None


def test_parse_refinement_offset_extracts_number_from_prose():
    """The model is told to return a bare int — but if it returns 'about 4500ms'
    we should still recover the number rather than dropping the call."""
    from app.services.providers import parse_refinement_offset

    assert parse_refinement_offset("about 4500ms") == 4500
    assert parse_refinement_offset("4500ms") == 4500


# ── get_ai_provider for boundary_refinement ──────────────────────────────────


def test_get_ai_provider_boundary_refinement_requires_gemini(session):
    """Boundary refinement only supports Gemini; an OpenAI model on the
    refinement slot must raise a clear ValueError."""
    provider_row, model = _openai_pair(supports_analysis=True)
    session.add(provider_row)
    session.add(model)
    session.commit()
    session.refresh(model)

    config = session.get(AppConfig, "config")
    config.boundary_refinement_model_id = model.id
    session.add(config)
    session.commit()
    session.refresh(config)

    with pytest.raises(ValueError, match="Boundary refinement requires a Gemini model"):
        get_ai_provider("boundary_refinement", config)


def test_get_ai_provider_boundary_refinement_returns_gemini_provider(session):
    from app.services.providers import GeminiProvider

    provider_row = AIProvider(kind="gemini", name="Gemini", api_key="k")
    model = AIModel(provider_id=provider_row.id, name="gemini-2.5-flash")
    model.provider = provider_row
    session.add(provider_row)
    session.add(model)
    session.commit()
    session.refresh(model)

    config = session.get(AppConfig, "config")
    config.boundary_refinement_model_id = model.id
    session.add(config)
    session.commit()
    session.refresh(config)

    provider = get_ai_provider("boundary_refinement", config)
    assert isinstance(provider, GeminiProvider)
    assert provider.model_config.name == "gemini-2.5-flash"


def test_get_ai_provider_boundary_refinement_requires_configured_model(session):
    """No refinement model on the AppConfig → ValueError."""
    config = session.get(AppConfig, "config")
    config.boundary_refinement_model_id = None
    session.add(config)
    session.commit()
    session.refresh(config)

    with pytest.raises(ValueError, match="No boundary refinement model configured"):
        get_ai_provider("boundary_refinement", config)
