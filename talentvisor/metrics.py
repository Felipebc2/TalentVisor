"""Cohen's kappa, WER, anonymization precision/recall, review and injection rates, latency.

REQ-Q-03. Metrics: docs/domain/metrics.md
"""
import re
import statistics
import unicodedata
from collections import Counter, defaultdict

from sqlmodel import Session, select

from talentvisor.db import AuditLog, Evaluation, RouterLog

AI_APPROVE_CUT = 3.5  # only for this metric: SPEC §10 has no cutoff, the AI never decides
MIN_DECISIONS = 3
_PLACEHOLDER = re.compile(r"\[[A-Z_]+\]")


def cohen_kappa(a: list, b: list) -> float | None:
    n = len(a)
    if n < 2 or n != len(b):
        return None
    po = sum(x == y for x, y in zip(a, b, strict=True)) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in ca) / n**2
    return None if pe == 1 else (po - pe) / (1 - pe)  # pe == 1: one label only, kappa undefined


def _words(text: str) -> list[str]:
    return re.sub(r"[^\w\s]", " ", text.casefold()).split()


def wer(reference: str, hypothesis: str) -> float:
    r, h = _words(reference), _words(hypothesis)
    prev = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        cur = [i]
        for j, hw in enumerate(h, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (rw != hw)))
        prev = cur
    return prev[-1] / len(r) if r else float(bool(h))


def _norm(s: str) -> str:
    return "".join(unicodedata.normalize("NFD", c)[0] for c in s).casefold()


def anonymization_pr(original: str, anonymized: str, pii: list[str]) -> tuple[float, float]:
    def count(text: str) -> int:
        t = _norm(text)
        return sum(len(re.findall(rf"(?<!\w){re.escape(_norm(p))}(?!\w)", t)) for p in pii if p.strip())

    total = count(original)
    removed = max(total - count(anonymized), 0)
    added = max(len(_PLACEHOLDER.findall(anonymized)) - len(_PLACEHOLDER.findall(original)), 0)
    recall = removed / total if total else 1.0
    precision = min(removed / added, 1.0) if added else float(removed == 0)
    return precision, recall


def summary(session: Session) -> dict:
    # latest evaluation per candidate: a re-run must not count the candidate twice
    evals = list({e.candidate_id: e for e in session.exec(select(Evaluation).order_by(Evaluation.id))}.values())
    n = len(evals)
    ms = defaultdict(list)
    # candidate runs only: eval/bias scripts and the text API log with candidate_id NULL
    for r in session.exec(select(RouterLog).where(RouterLog.ok, RouterLog.candidate_id != None)):  # noqa: E711
        ms[r.stage].append(r.ms)
    # latest recruiter decision per candidate (approve/reject only); later rows overwrite earlier ones
    human = {a.candidate_id: a.action for a in session.exec(select(AuditLog).where(
        AuditLog.actor == "recruiter", AuditLog.action.in_(["approve", "reject"])).order_by(AuditLog.id))}
    ai = {e.candidate_id: "approve" if e.overall_score >= AI_APPROVE_CUT else "reject"
          for e in evals if e.overall_score is not None}
    ids = [c for c in human if c in ai]
    return {
        "total": n,
        "review_rate": sum(e.human_review for e in evals) / n if n else None,
        "injection_rate": sum("injection_detected" in e.reasons for e in evals) / n if n else None,
        "latency_p50": {st: statistics.median(v) for st, v in sorted(ms.items())},
        "decisions": len(ids),
        "kappa": cohen_kappa([ai[c] for c in ids], [human[c] for c in ids]) if len(ids) >= MIN_DECISIONS else None,
    }
