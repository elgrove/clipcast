"""Recommended models per provider kind.

Mirrors the per-task recommendations the frontend shows when adding a model.
The frontend and backend must stay in sync — if you change a recommendation
here, update `ModelFormModal.svelte:getRecommended` too.
"""

from app.models import Provider


def recommended_models(kind: Provider) -> list[dict]:
    """Return the recommended (name, supports_transcription, supports_analysis)
    rows for a provider kind. Used when auto-creating models on provider create.

    Returns one row per task — gemini gets a single row that handles both;
    openai/openrouter get two rows (one tx-only, one an-only); whisper.cpp
    gets one tx-only row; openai-compatible gets none."""
    if kind == Provider.GEMINI:
        return [
            {
                "name": "gemini-2.5-flash",
                "supports_transcription": True,
                "supports_analysis": True,
            },
        ]
    if kind == Provider.OPENAI:
        return [
            {
                "name": "gpt-4o-mini-transcribe",
                "supports_transcription": True,
                "supports_analysis": False,
            },
            {
                "name": "gpt-4.1-mini",
                "supports_transcription": False,
                "supports_analysis": True,
            },
        ]
    if kind == Provider.OPENROUTER:
        return [
            {
                "name": "openai/whisper-large-v3",
                "supports_transcription": True,
                "supports_analysis": False,
            },
            {
                "name": "google/gemini-2.5-flash",
                "supports_transcription": False,
                "supports_analysis": True,
            },
        ]
    if kind == Provider.WHISPER_CPP:
        return [
            {
                "name": "whisper.cpp",
                "supports_transcription": True,
                "supports_analysis": False,
            },
        ]
    return []
