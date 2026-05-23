def test_list_providers_empty(client):
    response = client.get("/api/providers")
    assert response.status_code == 200
    assert response.json() == []


def test_create_gemini_provider_uses_canonical_name(client):
    response = client.post(
        "/api/providers",
        json={"kind": "gemini", "api_key": "key"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["kind"] == "gemini"
    assert data["name"] == "Gemini"
    assert data["has_api_key"] is True


def test_create_openai_compatible_requires_name(client):
    response = client.post(
        "/api/providers",
        json={"kind": "openai-compatible", "base_url": "https://api.groq.com/v1"},
    )
    assert response.status_code == 422
    assert "name is required" in response.json()["detail"].lower()


def test_create_openai_compatible_with_user_name(client):
    response = client.post(
        "/api/providers",
        json={
            "kind": "openai-compatible",
            "name": "Groq",
            "api_key": "k",
            "base_url": "https://api.groq.com/v1",
        },
    )
    assert response.status_code == 201
    assert response.json()["name"] == "Groq"


def test_single_instance_rule_for_canonical_providers(client):
    first = client.post("/api/providers", json={"kind": "gemini", "api_key": "a"})
    assert first.status_code == 201

    second = client.post("/api/providers", json={"kind": "gemini", "api_key": "b"})
    assert second.status_code == 422
    assert "already added" in second.json()["detail"].lower()


def test_multiple_openai_compatible_providers_allowed(client):
    a = client.post(
        "/api/providers",
        json={
            "kind": "openai-compatible",
            "name": "Groq",
            "api_key": "k",
            "base_url": "https://api.groq.com/v1",
        },
    )
    b = client.post(
        "/api/providers",
        json={
            "kind": "openai-compatible",
            "name": "Together",
            "api_key": "k",
            "base_url": "https://api.together.ai/v1",
        },
    )
    assert a.status_code == 201
    assert b.status_code == 201


def test_provider_name_must_be_unique(client):
    client.post(
        "/api/providers",
        json={
            "kind": "openai-compatible",
            "name": "Groq",
            "api_key": "k",
            "base_url": "https://x",
        },
    )
    dup = client.post(
        "/api/providers",
        json={
            "kind": "openai-compatible",
            "name": "Groq",
            "api_key": "k",
            "base_url": "https://y",
        },
    )
    assert dup.status_code == 422


def test_whisper_provider_requires_base_url(client):
    response = client.post("/api/providers", json={"kind": "whisper.cpp"})
    assert response.status_code == 422
    assert "host url is required" in response.json()["detail"].lower()


def test_openai_compatible_requires_base_url(client):
    response = client.post(
        "/api/providers",
        json={"kind": "openai-compatible", "name": "Groq", "api_key": "k"},
    )
    assert response.status_code == 422
    assert "base url is required" in response.json()["detail"].lower()


def test_update_provider_api_key(client):
    provider = client.post(
        "/api/providers", json={"kind": "gemini", "api_key": "old"}
    ).json()

    response = client.patch(
        f"/api/providers/{provider['id']}",
        json={"api_key": "new"},
    )
    assert response.status_code == 200
    assert response.json()["has_api_key"] is True


def test_delete_provider_blocked_if_models_exist(client):
    provider = client.post(
        "/api/providers", json={"kind": "gemini", "api_key": "k"}
    ).json()
    client.post(
        "/api/models",
        json={"provider_id": provider["id"], "name": "gemini-2.5-flash"},
    )

    response = client.delete(f"/api/providers/{provider['id']}")
    assert response.status_code == 422
    assert "models reference it" in response.json()["detail"].lower()


def test_delete_provider_succeeds_when_no_models(client):
    provider = client.post(
        "/api/providers", json={"kind": "gemini", "api_key": "k"}
    ).json()

    response = client.delete(f"/api/providers/{provider['id']}")
    assert response.status_code == 204
    assert client.get("/api/providers").json() == []


def test_auto_create_gemini_creates_one_dual_capability_model(client):
    provider = client.post(
        "/api/providers",
        json={"kind": "gemini", "api_key": "k", "auto_create_recommended": True},
    ).json()

    models = client.get("/api/models").json()
    gemini_models = [m for m in models if m["provider_id"] == provider["id"]]
    assert len(gemini_models) == 1
    m = gemini_models[0]
    assert m["name"] == "gemini-2.5-flash"
    assert m["supports_transcription"] is True
    assert m["supports_analysis"] is True

    config = client.get("/api/config").json()
    assert config["transcription_model_id"] == m["id"]
    assert config["analysis_model_id"] == m["id"]


def test_auto_create_openai_creates_two_split_capability_models(client):
    provider = client.post(
        "/api/providers",
        json={"kind": "openai", "api_key": "k", "auto_create_recommended": True},
    ).json()

    models = client.get("/api/models").json()
    openai_models = [m for m in models if m["provider_id"] == provider["id"]]
    assert len(openai_models) == 2
    tx = next(m for m in openai_models if m["supports_transcription"])
    an = next(m for m in openai_models if m["supports_analysis"])
    assert tx["name"] == "gpt-4o-mini-transcribe"
    assert tx["supports_analysis"] is False
    assert an["name"] == "gpt-4.1-mini"
    assert an["supports_transcription"] is False

    config = client.get("/api/config").json()
    assert config["transcription_model_id"] == tx["id"]
    assert config["analysis_model_id"] == an["id"]


def test_auto_create_openai_compatible_creates_no_models(client):
    provider = client.post(
        "/api/providers",
        json={
            "kind": "openai-compatible",
            "name": "Groq",
            "api_key": "k",
            "base_url": "https://api.groq.com/v1",
            "auto_create_recommended": True,
        },
    ).json()

    models = client.get("/api/models").json()
    assert not any(m["provider_id"] == provider["id"] for m in models)
