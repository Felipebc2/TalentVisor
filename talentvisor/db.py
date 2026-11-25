"""SQLModel tables, engine and TTL purge.

REQ-L-01, REQ-L-05. Schema: docs/architecture/data-model.md
"""
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import DateTime, TypeDecorator
from sqlmodel import Field, Session, SQLModel, create_engine, delete, select

DB_URL = os.environ.get("DB_URL", "sqlite:///data/talentvisor.db")
ORPHAN_HOURS = 6  # uploads older than this never reached the pipeline cleanup
TRANSCRIPT_TTL_DAYS = int(os.environ.get("TRANSCRIPT_TTL_DAYS", "7"))


class UTCDateTime(TypeDecorator):
    """SQLite drops tzinfo; store UTC and return aware datetimes."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return value.astimezone(UTC).replace(tzinfo=None) if value else value

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value else value


def now_utc() -> datetime:
    return datetime.now(UTC)


def _ts(**kw):
    return Field(default_factory=now_utc, sa_type=UTCDateTime, **kw)


def transcript_expiry() -> datetime:
    return now_utc() + timedelta(days=TRANSCRIPT_TTL_DAYS)


class Candidate(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    code: str = Field(unique=True, index=True)  # e.g. "TV-7F3A"
    real_name: str | None = None  # revealed only after the decision
    consent_at: datetime | None = Field(default=None, sa_type=UTCDateTime)
    consent_version: str | None = None
    cleared: bool = False
    status: str = "received"
    error: str | None = None  # failed stage (REQ-UI-10)
    video_path: str | None = None  # upload on disk; pipeline clears it after STT
    form_json: str = "{}"  # education, experience, description, answers P01-P05
    pii_json: str = "{}"  # name, institution, city: local-only (privacy.py), never sent to an LLM
    created_at: datetime = _ts()


class Transcript(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="candidate.id", index=True)
    text_anon: str = ""
    segments_json: str = "[]"
    quality_json: str = "{}"  # {avg_logprob, no_speech_prob, pct_inaudible}
    expires_at: datetime = Field(default_factory=transcript_expiry, sa_type=UTCDateTime)


class Evaluation(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    candidate_id: int = Field(foreign_key="candidate.id", index=True)
    result_json: str = "{}"
    overall_score: float | None = None
    category: str | None = None
    human_review: bool = False
    reasons: str = ""
    created_at: datetime = _ts()


class RouterLog(SQLModel, table=True):
    __tablename__ = "router_log"
    id: int | None = Field(default=None, primary_key=True)
    candidate_id: int | None = Field(default=None, index=True)
    stage: str
    model: str
    reason: str = ""
    fallback_from: str | None = None
    ms: int = 0
    ok: bool = True
    tokens: int = 0
    ts: datetime = _ts()


class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"
    id: int | None = Field(default=None, primary_key=True)
    candidate_id: int | None = Field(default=None, index=True)
    actor: str  # system | recruiter | candidate
    action: str
    payload_json: str = "{}"
    ts: datetime = _ts()


class LLMCache(SQLModel, table=True):
    __tablename__ = "llm_cache"
    key: str = Field(primary_key=True)  # sha256(model + prompt)
    response: str
    ts: datetime = _ts()


engine = create_engine(DB_URL, connect_args={"check_same_thread": False})


def init_db() -> None:
    if engine.url.get_backend_name() == "sqlite" and engine.url.database:
        Path(engine.url.database).parent.mkdir(parents=True, exist_ok=True)
    SQLModel.metadata.create_all(engine)


def purge_expired(now: datetime | None = None) -> dict[str, int]:
    """Delete rows past their TTL and orphan uploads; returns counts per table (+ orphan_videos)."""
    now = now or now_utc()
    d = lambda days: now - timedelta(days=days)  # noqa: E731
    rules = [
        (Transcript, Transcript.expires_at <= now),
        (Evaluation, Evaluation.created_at < d(30)),
        (Candidate, Candidate.created_at < d(30)),
        (RouterLog, RouterLog.ts < d(90)),
        (AuditLog, AuditLog.ts < d(90)),
        (LLMCache, LLMCache.ts < d(7)),
    ]
    with Session(engine) as s:
        # Orphan uploads first: also covers candidates about to be purged (>30 d), so no file outlives its row.
        orphans = s.exec(select(Candidate).where(
            Candidate.video_path != None,  # noqa: E711
            Candidate.created_at < now - timedelta(hours=ORPHAN_HOURS))).all()
        for c in orphans:
            Path(c.video_path).unlink(missing_ok=True)
            c.video_path = None
            if c.status in ("received", "transcribing"):
                c.status, c.error = "error", "transcribing"
            s.add(c)
        s.flush()
        counts = {m.__tablename__: s.exec(delete(m).where(w)).rowcount for m, w in rules}
        counts["orphan_videos"] = len(orphans)
        s.commit()
    return counts
