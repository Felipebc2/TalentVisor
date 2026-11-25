import pytest
from sqlmodel import Session, create_engine

from talentvisor import metrics
from talentvisor.db import AuditLog, Candidate, Evaluation, RouterLog


def test_kappa():
    assert metrics.cohen_kappa([1, 0, 1], [1, 0, 1]) == 1.0
    # a=[1,1,0,0,1,0], b=[1,0,0,0,1,1]: po=4/6; pe=(3*3 + 3*3)/36=0.5; kappa=(0.6667-0.5)/0.5=1/3
    assert metrics.cohen_kappa([1, 1, 0, 0, 1, 0], [1, 0, 0, 0, 1, 1]) == pytest.approx(1 / 3)
    assert metrics.cohen_kappa([1], [1]) is None
    assert metrics.cohen_kappa([1, 1], [1, 1]) is None  # undefined: single label


def test_wer():
    assert metrics.wer("o gato subiu", "o gato desceu") == pytest.approx(1 / 3)
    assert metrics.wer("O gato, subiu!", "o gato subiu") == 0
    assert metrics.wer("o gato subiu", "") == 1.0


def test_anonymization_pr():
    pii = ["Maria Silva", "UnB"]
    orig = "Maria Silva estudou na unb. Depois a Maria Silva trabalhou."
    assert metrics.anonymization_pr(orig, "[NOME] estudou na [INSTITUICAO]. Depois a [NOME] trabalhou.", pii) == (1.0, 1.0)
    # one occurrence missed, one extra placeholder on a non-PII word
    p, r = metrics.anonymization_pr(orig, "[NOME] estudou na unb. Depois a Maria Silva [LOCAL].", pii)
    assert (p, r) == (pytest.approx(1 / 2), pytest.approx(1 / 3))
    assert metrics.anonymization_pr("sem pii", "sem pii", pii) == (1.0, 1.0)


@pytest.fixture
def session(tmp_path, monkeypatch):
    from talentvisor import db

    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))
    db.init_db()
    with Session(db.engine) as s:
        yield s


def seed(s, n, score, review=False, reasons="", decision=None):
    c = Candidate(code=f"TV-{n:04d}")
    s.add(c)
    s.flush()
    s.add(Evaluation(candidate_id=c.id, overall_score=score, human_review=review, reasons=reasons))
    if decision:
        s.add(AuditLog(candidate_id=c.id, actor="recruiter", action=decision))
    s.commit()


def test_summary(session):
    assert metrics.summary(session)["review_rate"] is None
    seed(session, 1, 4.0, review=True, reasons="injection_detected", decision="approve")
    seed(session, 2, 2.0, decision="reject")
    session.add_all([RouterLog(stage="eval", model="m", ms=ms) for ms in (100, 300, 200)]
                    + [RouterLog(stage="eval", model="m", ms=9999, ok=False)])
    session.commit()
    m = metrics.summary(session)
    assert (m["total"], m["review_rate"], m["injection_rate"]) == (2, 0.5, 0.5)
    assert m["latency_p50"] == {"eval": 200} and m["kappa"] is None  # 2 decisions < 3
    seed(session, 3, 4.5, decision="approve")
    seed(session, 4, 1.0, decision="approve")  # disagreement
    assert metrics.summary(session)["kappa"] == pytest.approx(0.5)  # po=3/4, pe=0.5


def test_dashboard_renders_metrics(session):
    from fastapi.testclient import TestClient

    from talentvisor import app as a

    seed(session, 1, 4.0)
    html = TestClient(a.app).get("/dashboard").text
    assert "Métricas" in html and "Taxa de revisão" in html and "aguardando ≥ 3 decisões" in html
