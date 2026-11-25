from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, create_engine, select

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def db(tmp_path, monkeypatch):
    from talentvisor import db as m

    monkeypatch.setattr(m, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))
    m.init_db()
    return m


def ago(days):
    return NOW - timedelta(days=days)


def test_purge_expired(db):
    with Session(db.engine) as s:
        old = db.Candidate(code="TV-OLD1", created_at=ago(31))
        new = db.Candidate(code="TV-NEW1", created_at=ago(29))
        s.add_all([old, new])
        s.commit()
        s.add_all([
            db.Transcript(candidate_id=new.id, expires_at=NOW + timedelta(days=1)),  # created 6 d ago
            db.Transcript(candidate_id=new.id, expires_at=NOW - timedelta(days=1)),  # created 8 d ago
            db.Evaluation(candidate_id=old.id, created_at=ago(31)),
            db.Evaluation(candidate_id=new.id, created_at=ago(29)),
            db.RouterLog(stage="E3", model="m", ts=ago(91)),
            db.RouterLog(stage="E3", model="m", ts=ago(89)),
            db.AuditLog(actor="system", action="a", ts=ago(91)),
            db.AuditLog(actor="system", action="b", ts=ago(89)),
            db.LLMCache(key="old", response="x", ts=ago(8)),
            db.LLMCache(key="new", response="x", ts=ago(6)),
        ])
        s.commit()

    counts = db.purge_expired(now=NOW)
    assert counts == {"transcript": 1, "evaluation": 1, "candidate": 1,
                      "router_log": 1, "audit_log": 1, "llm_cache": 1, "orphan_videos": 0}

    with Session(db.engine) as s:
        assert [c.code for c in s.exec(select(db.Candidate))] == ["TV-NEW1"]
        t = s.exec(select(db.Transcript)).one()
        assert t.expires_at == NOW + timedelta(days=1) and t.expires_at.tzinfo is not None
        assert s.exec(select(db.LLMCache)).one().key == "new"
        assert s.exec(select(db.AuditLog)).one().action == "b"


def test_purge_orphan_videos(db, tmp_path):
    old, new = tmp_path / "old.mp4", tmp_path / "new.mp4"
    old.write_bytes(b"x"), new.write_bytes(b"x")
    with Session(db.engine) as s:
        s.add_all([
            db.Candidate(code="TV-ORPH", created_at=NOW - timedelta(hours=7), video_path=str(old)),
            db.Candidate(code="TV-FRSH", created_at=NOW - timedelta(hours=1), video_path=str(new)),
        ])
        s.commit()
    assert db.purge_expired(now=NOW)["orphan_videos"] == 1
    assert not old.exists() and new.exists()
    with Session(db.engine) as s:
        o = s.exec(select(db.Candidate).where(db.Candidate.code == "TV-ORPH")).one()
        f = s.exec(select(db.Candidate).where(db.Candidate.code == "TV-FRSH")).one()
        assert (o.video_path, o.status, o.error) == (None, "error", "transcribing")
        assert (f.video_path, f.status) == (str(new), "received")


def test_purge_orphan_tmp_chunks(db, tmp_path, monkeypatch):
    import os

    up = tmp_path / "up"
    monkeypatch.setattr(db, "UPLOAD_DIR", up)
    old, new = up / "tmpold", up / "tmpnew"
    for d, hours in ((old, 7), (new, 1)):
        d.mkdir(parents=True)
        (d / "c000.mp3").write_bytes(b"x")
        ts = (NOW - timedelta(hours=hours)).timestamp()
        os.utime(d, (ts, ts))
    keep = up / "video.mp4"
    keep.write_bytes(b"x")
    db.purge_expired(now=NOW)
    assert not old.exists() and new.exists() and keep.exists()


def test_startup_fails_inflight(db, tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"x")
    with Session(db.engine) as s:
        s.add_all([
            db.Candidate(code="TV-WEB1", status="scoring", consent_version="v1", video_path=str(video)),
            db.Candidate(code="TV-WEB2", status="received", consent_version="v1-groq", created_at=ago(2)),
            db.Candidate(code="TV-DATA", status="scoring", consent_version="dataset"),
            db.Candidate(code="TV-DONE", status="awaiting_decision", consent_version="v1"),
        ])
        s.commit()
    assert db.fail_inflight() == 2
    assert not video.exists()
    with Session(db.engine) as s:
        got = {c.code: (c.status, c.error, c.video_path) for c in s.exec(select(db.Candidate))}
        audits = sorted(a.payload_json for a in s.exec(select(db.AuditLog))
                        if a.actor == "system" and a.action == "error")
    assert got == {"TV-WEB1": ("error", "scoring", None), "TV-WEB2": ("error", "received", None),
                   "TV-DATA": ("scoring", None, None), "TV-DONE": ("awaiting_decision", None, None)}
    assert audits == ['{"stage": "received"}', '{"stage": "scoring"}']


def test_purge_redacts_audit_text_of_purged_candidate(db):
    with Session(db.engine) as s:
        old = db.Candidate(code="TV-OLD1", created_at=ago(31))
        new = db.Candidate(code="TV-NEW1", created_at=ago(29))
        s.add_all([old, new])
        s.commit()
        s.add_all([db.AuditLog(candidate_id=old.id, actor="candidate", action="contest", payload_json='{"text": "segredo"}', ts=ago(31)),
                   db.AuditLog(candidate_id=new.id, actor="candidate", action="contest", payload_json='{"text": "fica"}', ts=ago(29))])
        s.commit()
    db.purge_expired(now=NOW)
    with Session(db.engine) as s:
        assert sorted(a.payload_json for a in s.exec(select(db.AuditLog))) == ['{"text": "fica"}', "{}"]


def test_purge_keeps_import_marker(db):
    """The import marker holds only the pseudonymous dataset_id, so a purged dataset row is not re-imported."""
    with Session(db.engine) as s:
        old = db.Candidate(code="TV-OLD2", created_at=ago(31))
        s.add(old)
        s.commit()
        s.add(db.AuditLog(candidate_id=old.id, actor="system", action="imported", payload_json='{"dataset_id": "C001"}', ts=ago(31)))
        s.commit()
    db.purge_expired(now=NOW)
    with Session(db.engine) as s:
        assert [a.payload_json for a in s.exec(select(db.AuditLog))] == ['{"dataset_id": "C001"}']
