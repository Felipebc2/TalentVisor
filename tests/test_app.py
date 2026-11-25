import json

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, create_engine, select

FORM = {"consent": "v1", "name": "Maria Silva Souza", "institution": "UnB", "city": "Brasília", "education": "Direito"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from talentvisor import app as a
    from talentvisor import db

    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))
    monkeypatch.setattr(a, "UPLOAD_DIR", tmp_path / "up")
    db.init_db()
    return TestClient(a.app, follow_redirects=False)


def post(client, filename="minha_entrevista.mp4", ctype="video/mp4", **over):
    return client.post("/upload", data={**FORM, **over}, files={"video": (filename, b"fake", ctype)})


def test_consent_page(client):
    r = client.get("/")
    assert r.status_code == 200 and "Termo de consentimento" in r.text and "required" in r.text


def test_upload_requires_consent(client):
    r = client.get("/upload")
    assert r.status_code == 303 and r.headers["location"] == "/?msg=consent"
    assert "Aceite o termo para continuar." in client.get("/?msg=consent").text
    assert "<script>" not in client.get("/?msg=<script>").text
    assert client.get("/upload?consent=v1").status_code == 200


def test_upload_without_consent_400(client):
    assert post(client, consent="").status_code == 400


def test_invalid_extension(client):
    r = post(client, "x.exe", "application/octet-stream", city="Goiânia")
    assert r.status_code == 400
    assert 'aria-invalid="true"' in r.text and 'value="Goiânia"' in r.text and "Formato inválido" in r.text


def test_upload_too_big(client, monkeypatch):
    from talentvisor import app as a

    monkeypatch.setattr(a, "MAX_BYTES", 2)
    assert post(client).status_code == 400
    assert not list(a.UPLOAD_DIR.glob("*"))


def test_upload_ok(client):
    from talentvisor import app as a
    from talentvisor import db

    r = post(client)
    assert r.status_code == 303 and r.headers["location"].startswith("/submitted/TV-")
    with Session(db.engine) as s:
        c = s.exec(select(db.Candidate)).one()
        assert c.status == "received" and c.consent_version == "v1" and c.code in r.headers["location"]
        path = c.video_path
        assert "video_path" not in json.loads(c.form_json)
        assert s.exec(select(db.AuditLog)).one().action == "submitted"
    assert path.startswith(str(a.UPLOAD_DIR)) and "minha_entrevista" not in path and path.endswith(".mp4")
    assert client.get(r.headers["location"]).status_code == 200
    assert client.get("/submitted/TV-0000").status_code == 404


def test_dashboard_has_no_names(client):
    assert "Nenhuma candidatura ainda." in client.get("/dashboard").text
    post(client)
    html = client.get("/dashboard").text
    assert "TV-" in html and "Maria" not in html and "Silva" not in html
    assert "Recomendação gerada por IA. Decisão final é humana." in html


def test_db_failure_deletes_file(client, monkeypatch):
    from talentvisor import app as a

    def boom(*_):
        raise RuntimeError("db down")

    monkeypatch.setattr(a.Session, "flush", boom)
    with pytest.raises(RuntimeError):
        post(client)
    assert not list(a.UPLOAD_DIR.glob("*"))


def test_huge_content_length_413(client):
    r = client.post("/upload", content=b"x", headers={"content-length": str(400 * 1024 * 1024)})
    assert r.status_code == 413
