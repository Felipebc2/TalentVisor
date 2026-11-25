import json

import pytest
from sqlmodel import Session, create_engine, select

from talentvisor import db, pipeline, prompts, stt

TEXT = "eu procuraria explicar de forma clara e simples, utilizando exemplos do cotidiano " + "palavra " * 40


def _judge(score, evidence="explicar de forma clara"):
    d = json.loads(json.dumps(prompts.MOCK_JUDGE))
    for s in d["soft_skills"]:
        s["score"], s["evidence"] = score, evidence
    return prompts.JudgeOutput.model_validate(d)


def _aud(score):
    return prompts.AuditorOutput.model_validate({"scores": [{"skill": s, "score": score} for s in prompts.SKILLS]})


def agg(scores, aud=5, text=TEXT, evidence="explicar de forma clara"):
    runs = [_judge(s, evidence) for s in scores]
    return pipeline.aggregate(runs, _aud(aud), text, [{"start": 1.0, "end": 2.0, "text": text}])["soft_skills"][0]


def test_median_confidence():
    s = agg([5, 4, 5])
    assert s["score"] == 5 and s["run_scores"] == [5, 4, 5] and s["confidence"] == pytest.approx(0.76, abs=0.01)
    assert s["timestamp"] == [1.0, 2.0]
    assert agg([5, 5, 5])["confidence"] == 1.0
    s = agg([5, 3, 5])
    assert s["confidence"] == pytest.approx(0.53, abs=0.01)
    assert pipeline.triggers([s], injection=False, transcript_anon=TEXT, off_topic=0, quality={}) == ["low_confidence:communication"]


def test_missing_evidence():
    s = agg([5, 5, 5], evidence="isto nao existe")
    assert s["confidence"] == 0.3 and s["timestamp"] is None
    assert "low_confidence:communication" in pipeline.triggers([s], injection=False, transcript_anon=TEXT, off_topic=0, quality={})


def test_null_semantics():
    allnull = agg([None, None, None])
    assert allnull["score"] is None and allnull["confidence"] == 0.0
    assert pipeline.triggers([allnull], injection=False, transcript_anon=TEXT, off_topic=0, quality={}) == [
        "no_evidence:communication"]
    part = agg([None, 5, 5])
    assert part["score"] == 5 and part["confidence"] == 0.5
    assert pipeline.triggers([part], injection=False, transcript_anon=TEXT, off_topic=0, quality={}) == [
        "low_confidence:communication"]


def test_audit_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))  # never touch the dev DB
    monkeypatch.setenv("LLM_MODE", "mock")
    db.init_db()
    real = pipeline.router.call

    def call(stage, *a, **kw):
        if stage == "E6":
            raise pipeline.router.NoModelAvailable("down")
        return real(stage, *a, **kw)

    monkeypatch.setattr(pipeline.router, "call", call)
    res, _, _ = pipeline.evaluate_text(TEXT, [{"start": 0, "end": 1, "text": TEXT}], {}, {})
    assert "audit_unavailable" in res["reasons"] and res["human_review"] and res["models"]["auditor"] is None
    assert all(s["auditor_score"] is None for s in res["soft_skills"])


def test_review_triggers():
    def t(skill=None, **kw):
        base = dict(injection=False, transcript_anon=TEXT, off_topic=0, quality={"no_speech_prob": 0.1, "avg_logprob": -0.3})
        return pipeline.triggers([skill or agg([5, 5, 5], 5)], **{**base, **kw})

    assert t() == []
    assert t(agg([5, 5, 5], 3)) == ["divergence:communication"]
    assert t(injection=True) == ["injection_detected"]
    assert t(transcript_anon="poucas palavras") == ["empty_transcript"]
    assert t(off_topic=2) == ["off_topic"] and t(off_topic=1) == []
    assert t(quality={"no_speech_prob": 0.6, "avg_logprob": 0}) == ["low_audio_quality"]
    assert t(quality={"no_speech_prob": 0, "avg_logprob": -1.5}) == ["low_audio_quality"]


@pytest.fixture
def cand(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))
    monkeypatch.setenv("LLM_MODE", "mock")
    db.init_db()
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    with Session(db.engine) as s:
        c = db.Candidate(code="TV-AAAA", pii_json=json.dumps({"name": "Maria Silva Souza"}),
                         form_json=json.dumps({"education": "Direito", "experience": "", "description": "", "answers": {}}),
                         video_path=str(video))
        s.add(c)
        s.commit()
        return c.id, video


def _fake_stt(video, text):
    def fake(path):
        video.unlink()
        return {"segments": [{"start": 0.0, "end": 9.0, "text": text}], "text": text, "model": "fake-stt",
                "quality": {"avg_logprob": -0.2, "no_speech_prob": 0.05, "pct_inaudible": 0.0}}
    return fake


def test_full_mock_run(cand, monkeypatch):
    cid, video = cand
    text = "Meu nome é Maria Silva Souza. " + " ".join(m["text"] for m in prompts.MOCK_SEGMENTATION["answers"]) + " " + " ".join(
        s["evidence"] for s in prompts.MOCK_JUDGE["soft_skills"])
    monkeypatch.setattr(stt, "transcribe", _fake_stt(video, text))
    pipeline.run(cid)
    with Session(db.engine) as s:
        c = s.get(db.Candidate, cid)
        assert c.status == "awaiting_decision" and c.video_path is None and not video.exists()
        tr = s.exec(select(db.Transcript)).one()
        assert "Maria" not in tr.text_anon and "Maria" not in tr.segments_json
        ev = s.exec(select(db.Evaluation)).one()
        r = json.loads(ev.result_json)
        assert {"candidate_code", "soft_skills", "overall_score", "hard_skills", "work_profile", "personal_profile", "category",
                "category_rationale", "written_vs_spoken_consistency", "strengths", "concerns", "human_review", "reasons",
                "models"} <= r.keys()
        assert r["soft_skills"][0]["run_scores"] == [5, 5, 5] and r["soft_skills"][0]["timestamp"] == [0.0, 9.0]
        assert ev.overall_score == r["overall_score"] and ev.category == r["category"]
        logs = [x.stage for x in s.exec(select(db.RouterLog))]
        assert logs.count("E3") == 1 and logs.count("E4") == 3 and logs.count("E6") == 1
        acts = [(a.actor, a.action) for a in s.exec(select(db.AuditLog))]
        assert ("system", "evaluated") in acts and not any(a in ("approve", "reject") for _, a in acts)


def test_error_sets_status(cand, monkeypatch):
    cid, video = cand

    def boom(path):
        video.unlink()
        raise RuntimeError("secret Maria Silva Souza")

    monkeypatch.setattr(stt, "transcribe", boom)
    pipeline.run(cid)
    with Session(db.engine) as s:
        c = s.get(db.Candidate, cid)
        assert c.status == "error" and c.error == "transcribing" and not video.exists() and c.video_path is None
        a = s.exec(select(db.AuditLog).where(db.AuditLog.action == "error")).one()
        assert json.loads(a.payload_json) == {"stage": "transcribing"}


def test_no_system_decision_after_run(cand, monkeypatch):
    """REQ-L-03: the pipeline never writes a decision; only a human actor does."""
    cid, video = cand
    monkeypatch.setattr(stt, "transcribe", _fake_stt(video, TEXT))
    pipeline.run(cid)
    with Session(db.engine) as s:
        rows = s.exec(select(db.AuditLog).where(db.AuditLog.actor == "system")).all()
        assert rows and not {a.action for a in rows} & {"approve", "reject", "second_review"}
        assert s.get(db.Candidate, cid).status in ("awaiting_decision", "error")
