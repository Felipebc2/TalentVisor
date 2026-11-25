from fastapi.testclient import TestClient

from talentvisor.app import app


def test_health_reports_keys_without_leaking(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-fake-secret-123")
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("MISTRAL_API_KEY", raising=False)
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["keys"] == {"groq": True, "gemini": False, "mistral": False}
    assert isinstance(body["db"], bool) and isinstance(body["stt_model"], bool)
    assert "gsk-fake-secret-123" not in r.text


def test_health_503_when_db_down(monkeypatch):
    from talentvisor import app as a

    monkeypatch.setattr(a, "_db_ok", lambda: False)
    r = TestClient(app).get("/health")
    assert r.status_code == 503 and r.json()["db"] is False
