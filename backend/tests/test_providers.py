"""Tests for the OpenAI-compatible provider base class, OpenRouterProvider,
and the get_ai_provider() selector wiring for OpenRouter."""

from types import SimpleNamespace

import pytest

from app.models import (
    AIModel,
    AnalysisReport,
    AppConfig,
    PodcastEpisodeAdvert,
)
from app.services.providers import (
    ANALYSIS_TIMEOUT,
    OpenAICompatibleProvider,
    OpenRouterProvider,
    PodcastEpisodeAdverts,
    Transcription,
    get_ai_provider,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _openrouter_model(api_key: str = "sk-or-v1-test") -> AIModel:
    return AIModel(
        name="anthropic/claude-sonnet-4",
        provider="openrouter",
        api_key=api_key,
        input_price=0.0,
        output_price=0.0,
    )


def _fake_completion(*, cost: float | None = 0.0123, parsed_adverts=None):
    parsed = PodcastEpisodeAdverts(
        adverts=parsed_adverts
        or [
            PodcastEpisodeAdvert(
                start_time="00:00:10.000",
                end_time="00:00:25.000",
                advert_for="Squarespace",
                front_text="Today's episode is sponsored",
                tail_text="dot com slash clipcast",
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
    """Per-model api_key is required for OpenRouter."""
    model = _openrouter_model(api_key="")
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
    model = _openrouter_model()
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
    assert provider.model_config.api_key == "sk-or-v1-test"
    assert provider.model_config.name == "anthropic/claude-sonnet-4"


# ── OpenRouterProvider analyse_adverts ───────────────────────────────────────


def test_openrouter_provider_analyse_adverts_happy_path(monkeypatch):
    _patch_openai(monkeypatch, _fake_completion(cost=0.0042))

    provider = OpenRouterProvider(model_config=_openrouter_model())
    transcription = Transcription(segments=[])
    report = AnalysisReport()

    result = provider.analyse_adverts(transcription, report=report)

    assert len(result.adverts) == 1
    assert result.adverts[0].advert_for == "Squarespace"
    assert report.input_tokens == 1200
    assert report.output_tokens == 80
    assert report.cost_usd == 0.0042

    # Client was pointed at OpenRouter and given the leaderboard headers
    assert _FakeOpenAI.last_init_kwargs["base_url"] == "https://openrouter.ai/api/v1"
    assert _FakeOpenAI.last_init_kwargs["api_key"] == "sk-or-v1-test"
    call = _FakeOpenAI.last_call_kwargs
    assert call["model"] == "anthropic/claude-sonnet-4"
    assert call["response_format"] is PodcastEpisodeAdverts
    assert call["timeout"] == ANALYSIS_TIMEOUT
    assert call["extra_headers"] == {
        "HTTP-Referer": "https://github.com/elgrove/clipcast",
        "X-Title": "Clipcast",
    }
    assert call["extra_body"] == {"usage": {"include": True}}


def test_openrouter_provider_cost_falls_back_when_response_omits_cost(monkeypatch):
    _patch_openai(monkeypatch, _fake_completion(cost=None))

    model = _openrouter_model()
    model.input_price = 300  # arbitrary, just to prove calculate_cost ran
    model.output_price = 1500
    provider = OpenRouterProvider(model_config=model)
    report = AnalysisReport()

    provider.analyse_adverts(Transcription(segments=[]), report=report)

    # Fell back to calculate_cost() with the model's per-million prices
    expected = provider.calculate_cost(1200, 80, model)
    assert report.cost_usd == expected
    assert expected > 0


def test_openrouter_provider_appends_custom_instructions(monkeypatch):
    _patch_openai(monkeypatch, _fake_completion())

    provider = OpenRouterProvider(model_config=_openrouter_model())
    provider.analyse_adverts(
        Transcription(segments=[]),
        report=AnalysisReport(),
        custom_instructions="Ignore mentions of Patreon.",
    )

    prompt = _FakeOpenAI.last_call_kwargs["messages"][0]["content"]
    assert "Additional instructions:" in prompt
    assert "Ignore mentions of Patreon." in prompt


# ── Shared base class reuse ──────────────────────────────────────────────────


def test_openai_compatible_base_is_reusable_without_openrouter_overrides(monkeypatch):
    """A thin subclass with just a base_url should work end-to-end. This locks
    in that the base is genuinely reusable for future OpenAI / Groq / vLLM /
    etc. providers, and proves OpenRouter's cost extraction is the only
    OpenRouter-specific bit — not baked into the base."""

    _patch_openai(monkeypatch, _fake_completion(cost=99.99))  # ignored by base

    class _MyProvider(OpenAICompatibleProvider):
        base_url = "https://api.example.test/v1"

    model = AIModel(
        name="example/foo",
        provider="openrouter",
        api_key="example-key",
        input_price=0,
        output_price=0,
    )
    provider = _MyProvider(model_config=model)
    report = AnalysisReport()

    result = provider.analyse_adverts(Transcription(segments=[]), report=report)

    assert len(result.adverts) == 1
    assert report.input_tokens == 1200
    assert report.output_tokens == 80
    # Base _extract_cost returns None → falls back to calculate_cost (0 here)
    assert report.cost_usd == 0
    assert _FakeOpenAI.last_init_kwargs["base_url"] == "https://api.example.test/v1"
    # No extra_body unless subclass opts in
    assert "extra_body" not in _FakeOpenAI.last_call_kwargs
