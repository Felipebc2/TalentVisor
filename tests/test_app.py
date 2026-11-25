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
    calls = []
    monkeypatch.setattr("talentvisor.pipeline.run", calls.append)  # pipeline has its own tests; record the cids
    db.init_db()
    c = TestClient(a.app, follow_redirects=False)
    c.calls = calls
    return c


def post(client, filename="minha_entrevista.mp4", ctype="video/mp4", **over):
    return client.post("/upload", data={**FORM, **over}, files={"video": (filename, b"fake", ctype)})


def test_consent_page(client):
    r = client.get("/")
    assert r.status_code == 200 and "Termo de consentimento" in r.text and "required" in r.text


def test_upload_requires_consent(client):
    r = client.get("/upload")
    assert r.status_code == 303 and r.headers["location"] == "/?msg=consent"
    assert "Aceite o termo para continuar." in client.get("/?msg=consent").text
    assert "<script>xss" not in client.get("/?msg=<script>xss").text
    assert client.get("/upload?consent=v1").status_code == 200


def test_upload_without_consent_400(client):
    from talentvisor import db

    assert post(client, consent="").status_code == 400
    with Session(db.engine) as s:
        assert s.exec(select(db.Candidate)).all() == []
    assert client.calls == []


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
        assert c.consent_at is not None and client.calls == [c.id]
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


# --- T-14: dashboard, detail, decision, PDF, API ---


def seed(status="awaiting_decision", score=4, review=True, code="TV-AAAA"):
    from talentvisor import db
    from talentvisor.prompts import MOCK_JUDGE

    skills = [{**s, "timestamp": [12.4, 19.8], "run_scores": [5], "confidence": 0.8, "auditor_score": 4}
              for s in MOCK_JUDGE["soft_skills"]]
    skills[0]["score"] = score
    skills[1]["score"] = None
    result = {**MOCK_JUDGE, "candidate_code": "TV-AAAA", "soft_skills": skills, "overall_score": 4.2,
              "human_review": review, "reasons": ["divergence:ethics", "injection_detected"] if review else [], "models": {}}
    with Session(db.engine) as s:
        c = db.Candidate(code=code, status=status, real_name="Maria Silva Souza")
        s.add(c)
        s.flush()
        s.add(db.Evaluation(candidate_id=c.id, result_json=json.dumps(result), overall_score=4.2,
                            category="Comunicador Conciliador", human_review=review, reasons=",".join(result["reasons"])))
        s.add(db.RouterLog(candidate_id=c.id, stage="judge", model="m2", fallback_from="m1", ms=5))
        s.commit()
        return c.id


def test_rows_stop_polling(client):
    seed()
    r = client.get("/dashboard/rows")
    assert r.status_code == 286 and "TV-AAAA" in r.text and "Maria" not in r.text
    seed("scoring", code="TV-BBBB")
    assert client.get("/dashboard/rows").status_code == 200
    assert 'hx-trigger="every 3s"' in client.get("/dashboard").text


def test_dashboard_filters_and_review(client):
    seed()
    html = client.get("/dashboard").text
    assert "Revisão obrigatória" in html and "divergência em Ética" in html and "possível manipulação do prompt" in html
    assert "TV-AAAA" not in client.get("/dashboard?status=approved").text


def test_status_fragment(client):
    cid = seed("scoring")
    r = client.get(f"/candidate/{cid}/status")
    assert 'aria-current="step"' in r.text and "HX-Refresh" not in r.headers
    cid = seed("awaiting_decision", code="TV-CCCC")
    assert client.get(f"/candidate/{cid}/status").headers["HX-Refresh"] == "true"


def test_decision_writes_audit(client):
    from talentvisor import db

    cid = seed()
    assert "Maria" not in client.get(f"/candidate/{cid}").text
    r = client.post(f"/candidate/{cid}/decision", data={"decision": "reject", "comment": " "})
    assert r.status_code == 422 and "Comentário obrigatório para reprovar." in r.text
    r = client.post(f"/candidate/{cid}/decision", data={"decision": "approve", "comment": "bom"})
    assert r.status_code == 200 and "Aprovado para entrevista por recrutador em" in r.text
    assert r.headers["HX-Refresh"] == "true"
    with Session(db.engine) as s:
        a = s.exec(select(db.AuditLog).where(db.AuditLog.action == "approve")).one()
        assert a.actor == "recruiter" and json.loads(a.payload_json) == {"comment": "bom"}
        assert s.get(db.Candidate, cid).status == "approved"
    page = client.get(f"/candidate/{cid}").text
    assert "Maria Silva Souza" in page and ">Baixar PDF<" in page
    assert client.post(f"/candidate/{cid}/decision", data={"decision": "approve"}).status_code == 409
    assert 'value="approve"' not in page and 'value="second_review"' in page  # only reopening is offered
    r = client.post(f"/candidate/{cid}/decision", data={"decision": "second_review"})
    assert r.status_code == 200 and client.get(f"/candidate/{cid}").text.count('value="approve"') == 1
    assert client.post(f"/candidate/{cid}/decision", data={"decision": "reject", "comment": "x"}).status_code == 200


def test_dashboard_filter_empty_message(client):
    seed()
    assert "Nenhum resultado para o filtro." in client.get("/dashboard?status=approved").text


def test_no_system_decision():
    import re
    from pathlib import Path

    pat = re.compile(r"""actor\s*=\s*["']system["'][^)]*action\s*=\s*["'](approve|reject|second_review)""")
    for f in Path("talentvisor").glob("*.py"):
        assert not pat.search(f.read_text()), f


def test_detail_renders_skills(client):
    cid = seed()
    html = client.get(f"/candidate/{cid}").text
    assert "<meter" in html and "<blockquote>" in html and "<cite>P01 · 00:12–00:19</cite>" in html
    assert "sem evidência suficiente" in html and "REVISÃO HUMANA OBRIGATÓRIA" in html
    assert "Log do roteador" in html and 'class="fallback"' in html and "Baixar PDF (rascunho)" in html
    assert "Recomendação gerada por IA. Decisão final é humana." in html
    assert client.get("/candidate/999").status_code == 404


def test_detail_error_status(client):
    from talentvisor import db

    with Session(db.engine) as s:
        c = db.Candidate(code="TV-ERR1", status="error", error="scoring")
        s.add(c)
        s.commit()
        cid = c.id
    assert "Falha no processamento. Reenvie ou contate o suporte." in client.get(f"/candidate/{cid}").text


def test_api_candidate_json(client):
    cid = seed()
    r = client.get(f"/api/candidates/{cid}")
    assert r.status_code == 200 and r.json()["category"] == "Comunicador Conciliador"
    r = client.get("/api/candidates/999")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_api_evaluate(client, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    text = "Eu procuraria explicar de forma clara e simples. " * 5
    r = client.post("/api/evaluate", json={"text": text, "form": {}, "known": {}})
    assert r.status_code == 200
    assert {"soft_skills", "overall_score", "category", "human_review", "reasons", "models"} <= r.json().keys()
    assert client.post("/api/evaluate", json={"text": "  "}).status_code == 422
    assert client.post("/api/evaluate", json={}).status_code == 422


def test_pdf_route(client, monkeypatch):
    from talentvisor import report

    cid = seed()
    seen = {}
    monkeypatch.setattr(report, "render_pdf", lambda c, r, d: seen.update(d=d) or b"%PDF-fake")
    r = client.get(f"/candidate/{cid}/report.pdf")
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content == b"%PDF-fake"
    assert seen["d"] is None
    client.post(f"/candidate/{cid}/decision", data={"decision": "approve", "comment": "ok"})
    client.get(f"/candidate/{cid}/report.pdf")
    assert seen["d"]["action"] == "approve" and seen["d"]["comment"] == "ok"


def _contests():
    from talentvisor import db

    with Session(db.engine) as s:
        return s.exec(select(db.AuditLog).where(db.AuditLog.action == "contest")).all()


def test_contest_registers_audit(client):
    cid = seed()
    r = client.post("/contest", data={"code": "TV-AAAA", "text": "x" * 3000})
    assert r.status_code == 303 and r.headers["location"] == "/contest?msg=contested"
    assert "Contestação registrada" in client.get("/contest?msg=contested").text
    (a,) = _contests()
    assert a.candidate_id == cid and a.actor == "candidate" and len(json.loads(a.payload_json)["text"]) == 2000
    from talentvisor import db

    with Session(db.engine) as s:
        assert s.get(db.Candidate, cid).status == "awaiting_decision"  # REQ-L-03


def test_contest_unknown_code_same_message(client):
    seed()
    r = client.post("/contest", data={"code": "TV-ZZZZ", "text": "oi"})
    assert r.status_code == 303 and r.headers["location"] == "/contest?msg=contested"
    assert _contests() == []


def test_dashboard_shows_contested_badge(client):
    seed()
    assert "contestado" not in client.get("/dashboard").text
    client.post("/contest", data={"code": "TV-AAAA", "text": "revisem"})
    assert "contestado" in client.get("/dashboard").text


def test_contest_requires_fields(client):
    r = client.post("/contest", data={"code": "", "text": " "})
    assert r.status_code == 400 and r.text.count("Campo obrigatório.") == 2
    assert _contests() == []


def test_detail_lists_contests_escaped(client):
    cid = seed()
    assert "Contestações" not in client.get(f"/candidate/{cid}").text
    client.post("/contest", data={"code": "TV-AAAA", "text": "<b>revisem</b>"})
    page = client.get(f"/candidate/{cid}").text
    assert "Contestações" in page and "&lt;b&gt;revisem&lt;/b&gt;" in page and "<b>revisem" not in page


def test_name_hidden_again_after_second_review(client):
    cid = seed()
    client.post(f"/candidate/{cid}/decision", data={"decision": "approve", "comment": "ok"})
    assert "Maria Silva Souza" in client.get(f"/candidate/{cid}").text
    client.post(f"/candidate/{cid}/decision", data={"decision": "second_review"})
    assert "Maria Silva Souza" not in client.get(f"/candidate/{cid}").text  # D-041


def test_api_evaluate_errors_are_json(client, monkeypatch):
    from talentvisor import app as a
    from talentvisor import pipeline

    c = TestClient(a.app, raise_server_exceptions=False)
    body = {"text": "texto de teste " * 5}
    assert c.post("/api/evaluate", json={**body, "form": "x"}).json() == {"detail": "form and known must be objects"}

    def down(*_a, **_k):
        raise pipeline.router.NoModelAvailable("all providers down")
    monkeypatch.setattr(pipeline, "evaluate_text", down)
    r = c.post("/api/evaluate", json=body)
    assert r.status_code == 503 and r.json() == {"detail": "no model available"}

    def boom(*_a, **_k):
        raise RuntimeError("secret Maria Silva Souza")
    monkeypatch.setattr(pipeline, "evaluate_text", boom)
    r = c.post("/api/evaluate", json=body)
    assert r.status_code == 500 and r.json() == {"detail": "internal error"} and "Maria" not in r.text


def test_api_evaluate_writes_audit(client, monkeypatch):
    from talentvisor import db

    monkeypatch.setenv("LLM_MODE", "mock")
    r = client.post("/api/evaluate", json={"text": "Eu procuraria explicar de forma clara e simples. " * 5})
    with Session(db.engine) as s:
        a = s.exec(select(db.AuditLog).where(db.AuditLog.action == "evaluated_api")).one()
    assert a.actor == "system" and a.candidate_id is None
    assert json.loads(a.payload_json) == {"human_review": r.json()["human_review"], "reasons": r.json()["reasons"]}


def test_consent_names_groq_when_cloud_stt(client, monkeypatch):
    from talentvisor import app as a

    groq_audio = "o áudio do vídeo é enviado à Groq"
    html = client.get("/").text
    assert groq_audio not in html and "/contest" in html and "versão v1" in html
    monkeypatch.setattr(a, "CLOUD_STT", True)
    monkeypatch.setattr(a, "CONSENT_VERSION", "v1-groq")
    html = client.get("/").text
    assert groq_audio in html and "versão v1-groq" in html


def test_refused_row_has_no_open_link(client):
    cid = seed("refused")
    html = client.get("/dashboard/rows").text
    assert "TV-AAAA" in html and f'href="/candidate/{cid}"' not in html


def test_not_found_html_and_api_json(client):
    r = client.get("/nao-existe")
    assert r.status_code == 404 and "Página não encontrada." in r.text and "<html" in r.text.lower()
    r = client.get("/api/nao-existe")
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}


def test_detail_shows_router_log(client):
    cid = seed()
    html = client.get(f"/candidate/{cid}").text
    assert "Log do roteador" in html and "<td>m2</td>" in html and 'class="fallback"' in html


def test_upload_required_fields_and_csv_prefill(client):
    r = post(client, institution="")
    assert r.status_code == 400 and "Campo obrigatório." in r.text
    csv = "nome_pseudonimo;formacao_direito;experiencia_resumida\nAna Lima;Direito;Estágio\n".encode()
    r = client.post("/upload", data={**FORM, "name": "", "education": "Direito UnB"},
                    files={"video": ("v.mp4", b"fake", "video/mp4"), "csv": ("c.csv", csv, "text/csv")})
    assert r.status_code == 303  # CSV pre-filled the empty name
    from talentvisor import db

    with Session(db.engine) as s:
        c = s.exec(select(db.Candidate)).one()
    assert c.real_name == "Ana Lima" and json.loads(c.form_json)["education"] == "Direito UnB"  # user value wins
    assert json.loads(c.form_json)["experience"] == "Estágio"


def test_decision_409_while_processing(client):
    from talentvisor import db

    for i, st in enumerate((*db.PROCESSING, "error", "refused")):
        cid = seed(st, code=f"TV-P{i:03d}")
        for action in ("approve", "reject", "second_review"):
            r = client.post(f"/candidate/{cid}/decision", data={"decision": action, "comment": "x"})
            assert r.status_code == 409, (st, action)
    with Session(db.engine) as s:
        assert not s.exec(select(db.AuditLog).where(db.AuditLog.actor == "recruiter")).all()


def test_decision_requires_choice(client):
    cid = seed()
    r = client.post(f"/candidate/{cid}/decision", data={"comment": "x"})
    assert r.status_code == 422 and "Escolha uma decisão." in r.text


def test_detail_shows_source_side_by_side(client):
    """UI-17: transcript lines with timestamps, anonymized written form, video-deleted note; no real name before decision."""
    from talentvisor import db

    cid = seed()
    with Session(db.engine) as s:
        c = s.get(db.Candidate, cid)
        c.pii_json = json.dumps({"name": "Maria Silva Souza"})
        c.form_json = json.dumps({"education": "Direito", "experience": "", "description": "Sou Maria Silva Souza, gosto de mediar.",
                                  "answers": {"P01": "Explico com exemplos."}})
        s.add(c)
        s.add(db.Transcript(candidate_id=cid, text_anon="[NOME] explica",
                            segments_json=json.dumps([{"start": 12.4, "end": 19.8, "text": "[NOME] explicaria com exemplos"}]),
                            quality_json=json.dumps({"avg_logprob": -0.3, "no_speech_prob": 0.05, "pct_inaudible": 0.0})))
        s.commit()
    html = client.get(f"/candidate/{cid}").text
    assert 'id="t-12"' in html and "00:12" in html and 'href="#t-12"' in html  # evidence links to the transcript line
    assert "Vídeo apagado após a transcrição (LGPD)" in html and "<video" not in html
    assert "Explico com exemplos." in html and "gosto de mediar" in html and "Maria" not in html
