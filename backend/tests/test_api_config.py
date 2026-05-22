def test_get_config(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "transcription_model_id" in data
    assert "analysis_model_id" in data


def test_list_models_empty_by_default(client):
    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json() == []


def test_add_custom_model(client):
    response = client.post(
        "/api/models",
        json={
            "name": "my-custom-model",
            "provider": "gemini",
            "api_key": "test-key",
            "supports_transcription": True,
            "supports_analysis": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "my-custom-model"
    assert data["api_key"] == "test-key"
    assert data["supports_transcription"] is True
    assert data["supports_analysis"] is True


def test_add_custom_openrouter_model(client):
    response = client.post(
        "/api/models",
        json={
            "name": "anthropic/claude-sonnet-4",
            "provider": "openrouter",
            "host": "",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "anthropic/claude-sonnet-4"
    assert data["provider"] == "openrouter"
    assert data["is_preset"] is False

    listed = client.get("/api/models").json()
    assert any(m["name"] == "anthropic/claude-sonnet-4" for m in listed)


def test_update_model(client):
    created = client.post(
        "/api/models",
        json={
            "name": "gemini-2.5-flash",
            "provider": "gemini",
            "api_key": "",
            "supports_transcription": True,
            "supports_analysis": True,
        },
    ).json()

    response = client.put(
        f"/api/models/{created['id']}",
        json={"api_key": "my-gemini-key"},
    )
    assert response.status_code == 200
    assert response.json()["api_key"] == "my-gemini-key"


def test_delete_model(client):
    resp = client.post(
        "/api/models",
        json={"name": "to-delete", "provider": "gemini"},
    )
    model_id = resp.json()["id"]

    response = client.delete(f"/api/models/{model_id}")
    assert response.status_code == 204

    models = client.get("/api/models").json()
    assert not any(m["id"] == model_id for m in models)


def test_capability_validation_transcription(client):
    """Cannot set an analysis-only model as transcription model."""
    analysis_only = client.post(
        "/api/models",
        json={
            "name": "gpt-4.1-mini",
            "provider": "openai-compatible",
            "base_url": "https://api.openai.com/v1",
            "supports_transcription": False,
            "supports_analysis": True,
        },
    ).json()

    response = client.put(
        "/api/config",
        json={"transcription_model_id": analysis_only["id"]},
    )
    assert response.status_code == 422
    assert "transcription" in response.json()["detail"].lower()


def test_capability_validation_analysis(client):
    """Cannot set a transcription-only model as analysis model."""
    transcription_only = client.post(
        "/api/models",
        json={
            "name": "whisper.cpp",
            "provider": "whisper.cpp",
            "base_url": "http://localhost:8080",
            "supports_transcription": True,
            "supports_analysis": False,
        },
    ).json()

    response = client.put(
        "/api/config",
        json={"analysis_model_id": transcription_only["id"]},
    )
    assert response.status_code == 422
    assert "analysis" in response.json()["detail"].lower()


def test_update_config_with_valid_models(client):
    gemini = client.post(
        "/api/models",
        json={
            "name": "gemini-2.5-flash",
            "provider": "gemini",
            "supports_transcription": True,
            "supports_analysis": True,
        },
    ).json()
    whisper = client.post(
        "/api/models",
        json={
            "name": "whisper.cpp",
            "provider": "whisper.cpp",
            "base_url": "http://localhost:8080",
            "supports_transcription": True,
            "supports_analysis": False,
        },
    ).json()

    response = client.put(
        "/api/config",
        json={
            "transcription_model_id": whisper["id"],
            "analysis_model_id": gemini["id"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["transcription_model_id"] == whisper["id"]
    assert data["analysis_model_id"] == gemini["id"]


def test_test_model_endpoint_missing(client):
    response = client.post("/api/models/nonexistent-id/test")
    assert response.status_code == 404
