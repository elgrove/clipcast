def test_get_config(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "gemini_api_key" in data
    assert data["gemini_api_key"] == ""


def test_update_config(client):
    response = client.put(
        "/api/config",
        json={
            "gemini_api_key": "test-key-123",
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["gemini_api_key"] == "test-key-123"

    # Verify persistence
    response = client.get("/api/config")
    assert response.json()["gemini_api_key"] == "test-key-123"


def test_list_models(client):
    response = client.get("/api/models")
    assert response.status_code == 200
    models = response.json()
    assert len(models) == 3
    names = {m["name"] for m in models}
    assert "gemini-2.5-flash" in names
    assert "whisper.cpp" in names


def test_add_custom_model(client):
    response = client.post(
        "/api/models",
        json={
            "name": "my-custom-model",
            "provider": "gemini",
            "host": "",
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "my-custom-model"
    assert data["is_preset"] is False

    # Verify it appears in list
    response = client.get("/api/models")
    assert len(response.json()) == 4


def test_update_config_openrouter_key_round_trip(client):
    response = client.put(
        "/api/config",
        json={"openrouter_api_key": "sk-or-v1-test"},
    )
    assert response.status_code == 200
    assert response.json()["openrouter_api_key"] == "sk-or-v1-test"

    response = client.get("/api/config")
    assert response.json()["openrouter_api_key"] == "sk-or-v1-test"


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


def test_update_config_with_model(client):
    models = client.get("/api/models").json()
    gemini_model = next(m for m in models if m["name"] == "gemini-2.5-flash")

    response = client.put(
        "/api/config",
        json={
            "transcription_model_id": gemini_model["id"],
            "analysis_model_id": gemini_model["id"],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["transcription_model_id"] == gemini_model["id"]
    assert data["transcription_model"]["name"] == "gemini-2.5-flash"
