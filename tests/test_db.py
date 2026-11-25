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
