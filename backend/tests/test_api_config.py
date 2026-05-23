def test_get_config(client):
    response = client.get("/api/config")
    assert response.status_code == 200
    data = response.json()
    assert "transcription_model_id" in data
    assert "analysis_model_id" in data
    assert data["keep_raw_episodes"] is True


def test_update_keep_raw_episodes(client):
    response = client.put("/api/config", json={"keep_raw_episodes": False})
    assert response.status_code == 200
    assert response.json()["keep_raw_episodes"] is False

    response = client.put("/api/config", json={"keep_raw_episodes": True})
    assert response.status_code == 200
    assert response.json()["keep_raw_episodes"] is True


def test_list_models_empty_by_default(client):
    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json() == []


def _create_gemini_provider(client, api_key="test-key", auto_create=False):
    return client.post(
        "/api/providers",
        json={
            "kind": "gemini",
            "api_key": api_key,
            "auto_create_recommended": auto_create,
        },
    )


def test_add_custom_model(client):
    provider = _create_gemini_provider(client).json()

    response = client.post(
        "/api/models",
        json={
            "provider_id": provider["id"],
            "name": "my-custom-model",
            "supports_transcription": True,
            "supports_analysis": True,
        },
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "my-custom-model"
    assert data["provider_kind"] == "gemini"
    assert data["provider_name"] == "Gemini"
    assert data["supports_transcription"] is True
    assert data["supports_analysis"] is True


def test_create_model_requires_existing_provider(client):
    response = client.post(
        "/api/models",
        json={
            "provider_id": "nonexistent-provider-id",
            "name": "anything",
            "supports_transcription": True,
        },
    )
    assert response.status_code == 422
    assert "provider not found" in response.json()["detail"].lower()


def test_create_model_duplicate_name_on_same_provider(client):
    provider = _create_gemini_provider(client).json()

    first = client.post(
        "/api/models",
        json={"provider_id": provider["id"], "name": "gemini-2.5-flash"},
    )
    assert first.status_code == 201

    second = client.post(
        "/api/models",
        json={"provider_id": provider["id"], "name": "gemini-2.5-flash"},
    )
    assert second.status_code == 422
    assert "already exists" in second.json()["detail"].lower()


def test_update_model(client):
    provider = _create_gemini_provider(client).json()
    created = client.post(
        "/api/models",
        json={
            "provider_id": provider["id"],
            "name": "gemini-2.5-flash",
            "supports_transcription": True,
            "supports_analysis": True,
        },
    ).json()

    response = client.put(
        f"/api/models/{created['id']}",
        json={"supports_analysis": False},
    )
    assert response.status_code == 200
    assert response.json()["supports_analysis"] is False


def test_delete_model(client):
    provider = _create_gemini_provider(client).json()
    created = client.post(
        "/api/models",
        json={"provider_id": provider["id"], "name": "to-delete"},
    ).json()

    response = client.delete(f"/api/models/{created['id']}")
    assert response.status_code == 204

    models = client.get("/api/models").json()
    assert not any(m["id"] == created["id"] for m in models)


def test_capability_validation_transcription(client):
    """Cannot set an analysis-only model as transcription model."""
    provider = _create_gemini_provider(client).json()
    analysis_only = client.post(
        "/api/models",
        json={
            "provider_id": provider["id"],
            "name": "gpt-4.1-mini",
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
    provider = client.post(
        "/api/providers",
        json={"kind": "whisper.cpp", "base_url": "http://localhost:8080"},
    ).json()
    transcription_only = client.post(
        "/api/models",
        json={
            "provider_id": provider["id"],
            "name": "whisper.cpp",
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
    gemini_provider = _create_gemini_provider(client).json()
    whisper_provider = client.post(
        "/api/providers",
        json={"kind": "whisper.cpp", "base_url": "http://localhost:8080"},
    ).json()

    gemini = client.post(
        "/api/models",
        json={
            "provider_id": gemini_provider["id"],
            "name": "gemini-2.5-flash",
            "supports_transcription": True,
            "supports_analysis": True,
        },
    ).json()
    whisper = client.post(
        "/api/models",
        json={
            "provider_id": whisper_provider["id"],
            "name": "whisper.cpp",
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
