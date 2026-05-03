def test_get_config(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "transcription_model_id" in data
    assert "analysis_model_id" in data


def test_list_models(client):
    response = client.get("/api/models")
    assert response.status_code == 200
    models = response.json()
    names = {m["name"] for m in models}
    assert "gemini-2.5-flash" in names
    assert "whisper.cpp" in names
    assert "gpt-4.1-mini" in names
    assert "google/gemini-2.5-flash" in names


def test_preset_model_capability_flags(client):
    models = client.get("/api/models").json()
    gemini_flash = next(m for m in models if m["name"] == "gemini-2.5-flash")
    assert gemini_flash["supports_transcription"] is True
    assert gemini_flash["supports_analysis"] is True
    assert gemini_flash["is_recommended"] is True

    whisper = next(m for m in models if m["name"] == "whisper.cpp")
    assert whisper["supports_transcription"] is True
    assert whisper["supports_analysis"] is False

    openrouter = next(m for m in models if m["name"] == "google/gemini-2.5-flash")
    assert openrouter["supports_transcription"] is False
    assert openrouter["supports_analysis"] is True


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
    assert data["is_preset"] is False
    assert data["api_key"] == "test-key"


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
    models = client.get("/api/models").json()
    gemini = next(m for m in models if m["name"] == "gemini-2.5-flash")

    response = client.put(
        f"/api/models/{gemini['id']}",
        json={"api_key": "my-gemini-key"},
    )
    assert response.status_code == 200
    assert response.json()["api_key"] == "my-gemini-key"


def test_delete_model(client):
    # Create then delete
    resp = client.post(
        "/api/models",
        json={"name": "to-delete", "provider": "gemini"},
    )
    model_id = resp.json()["id"]

    response = client.delete(f"/api/models/{model_id}")
    assert response.status_code == 204

    # No longer in list
    models = client.get("/api/models").json()
    assert not any(m["id"] == model_id for m in models)


def test_capability_validation_transcription(client):
    """Cannot set a non-transcription model as transcription model."""
    models = client.get("/api/models").json()
    # gpt-4.1-mini supports analysis only
    gpt = next(m for m in models if m["name"] == "gpt-4.1-mini")

    response = client.put(
        "/api/config",
        json={"transcription_model_id": gpt["id"]},
    )
    assert response.status_code == 422
    assert "transcription" in response.json()["detail"].lower()


def test_capability_validation_analysis(client):
    """Cannot set a non-analysis model as analysis model."""
    models = client.get("/api/models").json()
    whisper = next(m for m in models if m["name"] == "whisper.cpp")

    response = client.put(
        "/api/config",
        json={"analysis_model_id": whisper["id"]},
    )
    assert response.status_code == 422
    assert "analysis" in response.json()["detail"].lower()


def test_update_config_with_valid_models(client):
    models = client.get("/api/models").json()
    gemini = next(m for m in models if m["name"] == "gemini-2.5-flash")
    whisper = next(m for m in models if m["name"] == "whisper.cpp")

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
