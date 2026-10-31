from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


def test_liveness_endpoint() -> None:
    app = create_app(Settings())
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "Semyzbay"}
    assert response.headers["X-Request-ID"]


def test_openapi_contains_health_contract() -> None:
    app = create_app(Settings())
    schema = app.openapi()
    assert "/health" in schema["paths"]
    assert "/health/ready" in schema["paths"]
    assert "/api/v1/auth/login" in schema["paths"]
    assert "/api/v1/organizations" in schema["paths"]
    assert "/api/v1/users" in schema["paths"]
    assert "/api/v1/rag/retrieve" in schema["paths"]
    assert "/api/v1/conversations" in schema["paths"]
    assert "/api/v1/chat/messages" in schema["paths"]
    assert "/api/v1/chat/messages/stream" in schema["paths"]
    assert "/api/v1/speech/transcribe" in schema["paths"]
    assert "/api/v1/speech/synthesize" in schema["paths"]
    assert "/api/v1/speech/voices" in schema["paths"]
