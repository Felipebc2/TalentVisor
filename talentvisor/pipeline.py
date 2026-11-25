"""Pipeline E0-E6: transcribe, anonymize, guard, segment, judge x3 (median), audit, human-review triggers.

REQ-F-09, REQ-F-10, REQ-F-12, REQ-F-13, REQ-L-03
"""
import json
import os
import re
import statistics
from pathlib import Path

import openai
from sqlmodel import Session

from talentvisor import db, llm, prompts, router, stt
from talentvisor.privacy import anonymize, detect_injection, leaks_known_pii

JUDGE_RUNS = int(os.environ.get("JUDGE_RUNS", "3"))
MIN_WORDS = 30


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.casefold()).strip()


def _evidence_ok(evidence: str, transcript_anon: str) -> bool:
    ev = _norm(evidence).strip(" \t\n.,;:!?\"'()[]…-–—")
    return bool(ev) and ev in _norm(transcript_anon)


def _timestamp(evidence: str, segments: list[dict]) -> list[float] | None:
    ev = _norm(evidence).strip(" \t\n.,;:!?\"'()[]…-–—")
    for s in segments:
        if ev and ev in _norm(s["text"]):
            return [s["start"], s["end"]]
    return None


def aggregate(runs: list[prompts.JudgeOutput], auditor: prompts.AuditorOutput | None,
              transcript_anon: str, segments: list[dict]) -> dict:
    """Median/confidence per skill + profile fields from the first run (SPEC §6, D-024)."""
    aud = {a.skill: a.score for a in auditor.scores} if auditor else {}  # None: audit unavailable
    skills = []
    for skill in prompts.SKILLS:
        cands = [x for r in runs for x in r.soft_skills if x.skill == skill]
        scored = [x for x in cands if x.score is not None]
        item = {"skill": skill, "evidence": "", "question": cands[0].question, "timestamp": None,
                "justification": cands[0].justification, "score": None, "run_scores": [],
                "confidence": 0.0, "auditor_score": aud.get(skill)}
        if scored:
            scores = [x.score for x in scored]
            med = statistics.median(scores)
            pick = min(scored, key=lambda x: abs(x.score - med))  # first run equal to the median
            conf = 1 - min(1, statistics.pstdev(scores) / 2)
            if len(scored) < len(cands):  # some runs null: disagreement, force human review
                conf = min(conf, 0.5)
            ok = _evidence_ok(pick.evidence, transcript_anon)
            item.update(evidence=pick.evidence, question=pick.question, justification=pick.justification,
                        score=int(med) if med == int(med) else med, run_scores=scores,
                        confidence=round(conf if ok else 0.3, 2),
                        timestamp=_timestamp(pick.evidence, segments) if ok else None)
        skills.append(item)
    medians = [s["score"] for s in skills if s["score"] is not None]
    first = runs[0]
    return {
        "soft_skills": skills,
        "overall_score": round(statistics.mean(medians), 1) if medians else None,
        "hard_skills": [h.model_dump() for h in first.hard_skills],
        "work_profile": first.work_profile, "personal_profile": first.personal_profile,
        "category": first.category, "category_rationale": first.category_rationale,
        "written_vs_spoken_consistency": first.written_vs_spoken_consistency.model_dump(),
        "strengths": first.strengths, "concerns": first.concerns,
    }


def triggers(soft_skills: list[dict], *, injection: bool, transcript_anon: str,
             off_topic: int, quality: dict) -> list[str]:
    """Human-review reason codes (REQ-F-13)."""
    reasons = []
    for s in soft_skills:
        if s["score"] is not None and s["auditor_score"] is not None and abs(s["score"] - s["auditor_score"]) >= 2:
            reasons.append(f"divergence:{s['skill']}")
        if s["score"] is None:
            reasons.append(f"no_evidence:{s['skill']}")  # all runs null (F-09)
        elif s["confidence"] < 0.7:
            reasons.append(f"low_confidence:{s['skill']}")
    if injection:
        reasons.append("injection_detected")
    if len(transcript_anon.split()) < MIN_WORDS:
        reasons.append("empty_transcript")
    if off_topic >= 2:
        reasons.append("off_topic")
    if quality.get("no_speech_prob", 0) > 0.5 or quality.get("avg_logprob", 0) < -1.0:
        reasons.append("low_audio_quality")
    return reasons


def _update(cid: int, **fields) -> None:
    with Session(db.engine) as s:
        c = s.get(db.Candidate, cid)
        for k, v in fields.items():
            setattr(c, k, v)
        s.commit()


def _form_text(form: dict) -> str:
    parts = [form.get(k, "") for k in ("education", "experience", "description")]
    return "\n".join(parts + list(form.get("answers", {}).values()))


def evaluate_text(transcript: str, segments: list[dict], form: dict, known: dict, *, quality: dict | None = None,
                  candidate_id: int | None = None, candidate_code: str = "", on_stage=None) -> tuple[dict, str, list[dict]]:
    """E2-E6 on text: anonymize, guard, segment, judge x N, audit, aggregate. SPEC §6 result + anonymized text.

    Writes only router_log (via router.call). quality=None means text input (no audio signal).
    """
    stage = on_stage or (lambda name: None)
    q = quality or {}
    stage("anonymizing")
    text_anon = anonymize(transcript, known)
    segments_anon = [{**sg, "text": anonymize(sg["text"], known)} for sg in segments]
    form_anon = anonymize(_form_text(form), known)

    stage("scoring")
    full = f"{text_anon}\n{form_anon}"
    try:
        guard = llm.guard(full, known)
    except (openai.APIError, ValueError):
        guard = None  # no signal; the heuristic still runs
    injection = bool(detect_injection(full)) or (guard is not None and guard >= 0.5)
    low_audio = q.get("no_speech_prob", 0) > 0.5 or q.get("avg_logprob", 0) < -1.0
    ctx = {"has_pii": leaks_known_pii(full, known), "tokens": len(full) // 4, "complex": injection,
           "low_audio": low_audio, "demo": os.environ.get("DEMO_MODE") == "1"}
    cid = candidate_id
    seg, _ = router.call("E3", ctx, prompts.segment_messages(text_anon), prompts.Segmentation, known,
                         candidate_id=cid, mock=prompts.MOCK_SEGMENTATION)
    runs, judge_models = [], []
    for i in range(JUDGE_RUNS):  # distinct seed per run, else the cache returns the same answer
        out, meta = router.call("E4", ctx, prompts.judge_messages(seg, form_anon), prompts.JudgeOutput, known,
                                candidate_id=cid, temperature=0.7, seed=i, mock=prompts.MOCK_JUDGE)
        runs.append(out)
        judge_models.append(meta["model"])
    judge_model = judge_models[0]
    # No separate E5 call: the judge already returns profiles and strengths (orchestrator logs the decision).

    stage("auditing")
    # E6 must be a family none of the E4 runs used (D-040); the router drops those families, empty list -> human review
    families = {router.family(m) for m in judge_models}
    try:
        aud, ameta = router.call("E6", {**ctx, "judge_families": families}, prompts.auditor_messages(seg),
                                 prompts.AuditorOutput, known, candidate_id=cid, mock=prompts.MOCK_AUDITOR)
    except router.NoModelAvailable:
        aud, ameta = None, {"model": None}  # not an error: human review (F-12)

    res = aggregate(runs, aud, text_anon, segments_anon)
    reasons = triggers(res["soft_skills"], injection=injection, transcript_anon=text_anon,
                       off_topic=sum(a.off_topic for a in seg.answers), quality=q)
    if aud is None:
        reasons.append("audit_unavailable")
    result = {"candidate_code": candidate_code, **res, "human_review": bool(reasons), "reasons": reasons,
              "models": {"stt": None, "judge": judge_model, "auditor": ameta["model"]}}
    return result, text_anon, segments_anon


def _run(cid: int, stage: list) -> None:
    with Session(db.engine) as s:
        c = s.get(db.Candidate, cid)
        known, form, path, code = json.loads(c.pii_json), json.loads(c.form_json), c.video_path, c.code
        cloud_ok = c.consent_version == "v1-groq"  # only a consent that names Groq allows raw media to leave (L-04)

    stage[0] = "transcribing"
    _update(cid, status="transcribing")
    tr = stt.transcribe(path, allow_cloud=cloud_ok)  # deletes the file (REQ-L-01)
    _update(cid, video_path=None)

    text, segs, q = tr["text"], tr["segments"], tr["quality"]
    result, text_anon, segments = evaluate_text(
        text, segs, form, known, quality=q, candidate_id=cid, candidate_code=code,
        on_stage=lambda name: (stage.__setitem__(0, name), _update(cid, status=name)))
    result["models"]["stt"] = tr["model"]
    reasons, res = result["reasons"], result
    with Session(db.engine) as s:
        s.add(db.Transcript(candidate_id=cid, text_anon=text_anon, segments_json=json.dumps(segments, ensure_ascii=False),
                            quality_json=json.dumps(q)))
        s.add(db.Evaluation(candidate_id=cid, result_json=json.dumps(result, ensure_ascii=False),
                            overall_score=res["overall_score"], category=res["category"],
                            human_review=bool(reasons), reasons=",".join(reasons)))
        s.add(db.AuditLog(candidate_id=cid, actor="system", action="evaluated",
                          payload_json=json.dumps({"human_review": bool(reasons), "reasons": reasons})))
        s.commit()
    _update(cid, status="awaiting_decision")  # never a decision here (REQ-L-03)
    db.purge_expired()


def run(candidate_id: int) -> None:
    stage = ["transcribing"]
    try:
        _run(candidate_id, stage)
    except Exception:  # no stack trace is stored: it could carry PII
        with Session(db.engine) as s:
            c = s.get(db.Candidate, candidate_id)
            if c.video_path:
                Path(c.video_path).unlink(missing_ok=True)
            c.status, c.error, c.video_path = "error", stage[0], None
            s.add(db.AuditLog(candidate_id=candidate_id, actor="system", action="error",
                              payload_json=json.dumps({"stage": stage[0]})))
            s.commit()
