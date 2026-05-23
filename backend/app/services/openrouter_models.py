"""Lookup helpers for OpenRouter's model catalogue. The /api/v1/models endpoint
exposes every model's context_length, which we capture at model-creation time
so chunking knows how big a transcript the model can swallow in one call."""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)

MODELS_URL = "https://openrouter.ai/api/v1/models"
TIMEOUT_S = 15


def fetch_context_length(model_id: str, api_key: str = "") -> int:
    """Return the context window for an OpenRouter model id, or 0 if the lookup
    fails or the model isn't found. Caller falls back to a provider-level
    default in that case."""
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        resp = requests.get(MODELS_URL, headers=headers, timeout=TIMEOUT_S)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("OpenRouter model catalogue fetch failed: %s", e)
        return 0

    try:
        models = resp.json().get("data", [])
    except ValueError as e:
        logger.warning("OpenRouter model catalogue returned invalid JSON: %s", e)
        return 0

    for entry in models:
        if entry.get("id") == model_id:
            value = entry.get("context_length") or 0
            try:
                return int(value)
            except (TypeError, ValueError):
                logger.warning(
                    "OpenRouter model %s has unparseable context_length=%r",
                    model_id,
                    value,
                )
                return 0

    logger.warning("OpenRouter model %s not found in catalogue", model_id)
    return 0
