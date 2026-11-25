"""FastAPI routes: candidate pages, recruiter dashboard, decision, PDF, JSON API and /health.

REQ-F-01, REQ-F-02, REQ-F-14..17, REQ-NF-03, REQ-NF-04, REQ-NF-06. UI: docs/spec/ui.md
"""

import json
import os
import secrets
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from talentvisor import db, metrics, pipeline, privacy, report, stt
from talentvisor.db import PROCESSING, AuditLog, Candidate, Evaluation, RouterLog, Transcript, now_utc
from talentvisor.prompts import QUESTIONS, SKILL_LABELS
from talentvisor.report import reason_label

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=BASE / "templates")  # autoescape on for .html

CLOUD_STT = os.environ.get("ALLOW_CLOUD_STT") == "1"  # read at start: the consent must name Groq (L-04, D-035)
CONSENT_VERSION = "v1-groq" if CLOUD_STT else "v1"
MAX_BYTES = 300 * 1024 * 1024
UPLOAD_DIR = db.UPLOAD_DIR
VIDEO_TYPES = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"}
FLASH = {"consent": "Aceite o termo para continuar."}  # fixed texts: never echo user input
TEXT_FIELDS = ("name", "institution", "city", "education", "experience", "description")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    db.fail_inflight()  # BackgroundTasks die with the process: nothing is really in flight at startup
    db.purge_expired()
    yield


app = FastAPI(title="TalentVisor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


def render(request: Request, name: str, status: int = 200, **ctx):
    return templates.TemplateResponse(request, name, {"flash": FLASH.get(request.query_params.get("msg")), **ctx}, status_code=status)


def error_page(request: Request, status: int, message: str):
    return render(request, "error.html", status, status_code=status, message=message)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    msg = "Página não encontrada." if exc.status_code == 404 else "Requisição inválida."
    return error_page(request, exc.status_code, msg)


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception):
    if request.url.path.startswith("/api/"):  # Langflow gets JSON, never HTML (§7, D-050); no exception text (may carry PII)
        if isinstance(exc, pipeline.router.NoModelAvailable):
            return JSONResponse({"detail": "no model available"}, status_code=503)
        return JSONResponse({"detail": "internal error"}, status_code=500)
    return error_page(request, 500, "Algo deu errado. Tente novamente em instantes.")


def _db_ok() -> bool:
    try:
        with db.engine.connect() as con:  # the configured DB_URL, not a hardcoded path
            return con.exec_driver_sql("select 1").scalar() == 1
    except Exception:
        return False


def _stt_ok() -> bool:
    try:  # local files only: no load, no download
        from faster_whisper.utils import download_model

        download_model(stt.MODEL, local_files_only=True)
        return True
    except Exception:
        return False


@app.get("/health")
def health():
    body = {
        "db": _db_ok(),
        "stt_model": _stt_ok(),
        "keys": {"groq": bool(os.environ.get("GROQ_API_KEY")), "gemini": bool(os.environ.get("GEMINI_API_KEY")),
                 "mistral": bool(os.environ.get("MISTRAL_API_KEY"))},
    }
    # Missing keys don't fail health: mock mode runs without them (D-025).
    return JSONResponse(body, status_code=200 if body["db"] and body["stt_model"] else 503)


def upload_form(request: Request, status: int = 200, values=None, errors=None):
    return render(request, "upload.html", status, questions=QUESTIONS.items(), version=CONSENT_VERSION,
                  cloud_stt=CLOUD_STT, v=values or {}, errors=errors or {})


@app.get("/")
@app.get("/upload")
def upload_page(request: Request):
    """The candidate lands on the form; consent is a required checkbox next to "Enviar" (D-062)."""
    return upload_form(request)


def _save_video(video) -> tuple[Path | None, str | None]:
    """Stream to data/uploads/<uuid><ext>; returns (path, error). Partial files are removed."""
    ext = Path(video.filename or "").suffix.lower()
    if ext not in VIDEO_TYPES or video.content_type not in VIDEO_TYPES.values():
        return None, "Formato inválido. Envie um vídeo .mp4, .webm ou .mov."
    if (video.size or 0) > MAX_BYTES:
        return None, "Arquivo maior que 300 MB."
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{uuid.uuid4()}{ext}"
    try:
        with path.open("wb") as out:
            shutil.copyfileobj(video.file, out)
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    return path, None


@app.post("/upload")
async def upload(request: Request, background_tasks: BackgroundTasks):
    if int(request.headers.get("content-length") or 0) > MAX_BYTES + 1_000_000:
        return error_page(request, 413, "Arquivo muito grande (máx. 300 MB).")
    form = await request.form()
    v = {k: str(form.get(k) or "").strip() for k in TEXT_FIELDS}
    v.update({p: str(form.get(p) or "").strip() for p in QUESTIONS})
    errors = {k: "Campo obrigatório." for k in ("name", "institution", "city", "education") if not v[k]}
    if form.get("consent") != CONSENT_VERSION:  # checked before the video is saved: no consent, no file kept
        errors["consent"] = "Aceite o termo de consentimento para enviar."
    video, path = form.get("video"), None
    if "consent" in errors:
        return upload_form(request, 400, v, errors)
    if video is None or not getattr(video, "filename", ""):
        errors["video"] = "Envie o vídeo."
    else:
        path, err = await run_in_threadpool(_save_video, video)
        if err:
            errors["video"] = err
    if errors:
        if path:
            path.unlink(missing_ok=True)
        return upload_form(request, 400, v, errors)

    form_json = {
        "education": v["education"], "experience": v["experience"], "description": v["description"],
        "answers": {p: v[p] for p in QUESTIONS},
    }
    try:
        with Session(db.engine) as s:
            while True:
                code = f"TV-{secrets.token_hex(2).upper()}"
                if not s.exec(select(Candidate).where(Candidate.code == code)).first():
                    break
            cand = Candidate(
                code=code, status="received", consent_at=now_utc(), consent_version=CONSENT_VERSION, cleared=True,
                real_name=v["name"], pii_json=json.dumps({k: v[k] for k in ("name", "institution", "city")}),
                form_json=json.dumps(form_json), video_path=str(path),  # video_path: pipeline only, cleared after STT
            )
            s.add(cand)
            s.flush()
            cid = cand.id
            s.add(AuditLog(candidate_id=cand.id, actor="candidate", action="submitted"))
            s.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    background_tasks.add_task(pipeline.run, cid)
    return RedirectResponse(f"/submitted/{code}", status_code=303)


@app.get("/submitted/{code}")
def submitted(request: Request, code: str):
    with Session(db.engine) as s:
        if not s.exec(select(Candidate).where(Candidate.code == code)).first():
            return error_page(request, 404, "Página não encontrada.")
    return render(request, "submitted.html", code=code)


DECIDABLE = ("awaiting_decision", "second_review")
FINAL = ("approved", "rejected")  # only "second_review" can reopen these
DECISION_STATUS = {"approve": "approved", "reject": "rejected", "second_review": "second_review"}
DECISION_TEXT = {"approve": "Aprovado para entrevista", "reject": "Reprovado", "second_review": "Enviado para segunda avaliação"}
STAGES = {"received": "recebido", "transcribing": "transcrição", "anonymizing": "anonimização", "scoring": "avaliação",
          "auditing": "auditoria"}
def _fmt_ts(dt) -> str:
    return dt.strftime("%d/%m %H:%M")


def _dtext(decision: dict | None) -> str:
    return f"{DECISION_TEXT[decision['action']]} por recrutador em {_fmt_ts(decision['ts'])}" if decision else ""


templates.env.globals.update(STAGES=STAGES, PROCESSING=PROCESSING, SKILL_LABELS=SKILL_LABELS, QUESTIONS=QUESTIONS,
                             # cache-busting: browsers kept a stale style.css (no version in the URL)
                             css_v=lambda: int((BASE / "static" / "style.css").stat().st_mtime))
templates.env.filters["mmss"] = lambda t: f"{int(t) // 60:02d}:{int(t) % 60:02d}"
templates.env.filters["reasons"] = lambda codes: [reason_label(c) for c in codes]


def _dash_rows(flt_status: str, review: bool):
    """(all counters, rows) for the recruiter list: review-first, then newest. No names."""
    with Session(db.engine) as s:
        evals = {e.candidate_id: e for e in s.exec(select(Evaluation).order_by(Evaluation.id))}  # later wins
        cands = s.exec(select(Candidate).order_by(Candidate.created_at.desc())).all()
    rows = []
    for c in cands:
        e = evals.get(c.id)
        rows.append({
            "id": c.id, "code": c.code, "status": c.status, "sent": _fmt_ts(c.created_at),
            "score": e.overall_score if e else None, "category": e.category if e else None,
            "review": bool(e and e.human_review), "reasons": [reason_label(r) for r in e.reasons.split(",") if r] if e else [],
        })
    counts = {
        "total": len(rows), "awaiting": sum(r["status"] == "awaiting_decision" for r in rows),
        "review": sum(r["review"] for r in rows), "decided": sum(r["status"] in ("approved", "rejected") for r in rows),
    }
    shown = [r for r in rows if (not flt_status or r["status"] == flt_status) and (not review or r["review"])]
    shown.sort(key=lambda r: not r["review"])  # stable: date desc is kept inside each group
    return counts, shown


@app.get("/dashboard")
def dashboard(request: Request, status: str = "", review: str = ""):
    counts, rows = _dash_rows(status, bool(review))
    with Session(db.engine) as s:
        m = metrics.summary(s)
    return render(request, "dashboard.html", rows=rows, counts=counts, f_status=status, f_review=bool(review),
                  metrics=m, qs=request.url.query, polling=any(r["status"] in PROCESSING for r in rows))


@app.get("/dashboard/rows")
def dashboard_rows(request: Request, status: str = "", review: str = ""):
    _, rows = _dash_rows(status, bool(review))
    busy = any(r["status"] in PROCESSING for r in rows)
    return render(request, "_rows.html", 200 if busy else 286, rows=rows)  # 286 stops HTMX polling (UI-06)


def _candidate_or_404(s: Session, cid: int) -> Candidate:
    c = s.get(Candidate, cid)
    if c is None:
        raise StarletteHTTPException(404)
    return c


def _decision(s: Session, cid: int) -> dict | None:
    """Latest recruiter decision as {action, comment, ts} (REQ-L-03: only these rows count as decisions)."""
    row = s.exec(select(AuditLog).where(AuditLog.candidate_id == cid, AuditLog.actor == "recruiter",
                                        AuditLog.action.in_(list(DECISION_STATUS))).order_by(AuditLog.id.desc())).first()
    if row is None:
        return None
    return {"action": row.action, "comment": json.loads(row.payload_json).get("comment", ""), "ts": row.ts}


def _evaluation(s: Session, cid: int) -> Evaluation | None:
    return s.exec(select(Evaluation).where(Evaluation.candidate_id == cid).order_by(Evaluation.id.desc())).first()


def _panel(request: Request, c: Candidate, decision, status: int = 200, error: str = ""):
    text = _dtext(decision)
    return render(request, "_decision.html", status, c=c, decision=decision, decision_text=text, error=error,
                  can_decide=c.status in DECIDABLE + FINAL, only_reopen=c.status in FINAL)


@app.get("/candidate/{cid}")
def candidate_page(request: Request, cid: int):
    with Session(db.engine) as s:
        c = _candidate_or_404(s, cid)
        ev, decision = _evaluation(s, cid), _decision(s, cid)
        result = json.loads(ev.result_json) if ev else None
        logs = s.exec(select(RouterLog).where(RouterLog.candidate_id == cid).order_by(RouterLog.id)).all()
        text = _dtext(decision)
        name = c.real_name if c.status in ("approved", "rejected") else None  # revealed only after a decision (UI-12)
        tr = s.exec(select(Transcript).where(Transcript.candidate_id == cid)).first()
        return render(request, "candidate.html", c=c, real_name=name, r=result, decision=decision, decision_text=text,
                      logs=logs, processing=c.status in PROCESSING, error="",
                      can_decide=c.status in DECIDABLE + FINAL, only_reopen=c.status in FINAL,
                      source=_source(c, tr))


def _source(c: Candidate, tr) -> dict:
    """What the candidate actually said and wrote, for reading next to the AI analysis (UI-17).

    The video itself is gone after STT (REQ-L-01): only the anonymized transcript, its audio
    quality and the written form remain. The form is anonymized with the known PII on the fly so
    the review stays blind until the decision (UI-12).
    """
    known, form = json.loads(c.pii_json or "{}"), json.loads(c.form_json or "{}")
    anon = (lambda t: privacy.anonymize(t, known)) if any(form.values()) else (lambda t: t)
    answers = form.get("answers") or {}
    written = {k: anon(str(form.get(k) or "")) for k in ("education", "experience", "description")}
    segs = json.loads(tr.segments_json) if tr else []
    return {
        "segments": segs, "quality": json.loads(tr.quality_json) if tr else {},
        "expires_at": _fmt_ts(tr.expires_at) if tr else None,
        "duration": segs[-1]["end"] if segs else None,
        "form": written, "answers": {q: anon(answers.get(q) or "") for q in QUESTIONS},
    }


@app.get("/candidate/{cid}/status")
def candidate_status(request: Request, cid: int):
    with Session(db.engine) as s:
        c = _candidate_or_404(s, cid)
    resp = render(request, "_status.html", c=c)
    if c.status not in PROCESSING:
        resp.headers["HX-Refresh"] = "true"  # leaves processing: reload the whole page (UI-09)
    return resp


@app.post("/candidate/{cid}/decision")
async def decide(request: Request, cid: int):
    form = await request.form()
    action, comment = str(form.get("decision") or ""), str(form.get("comment") or "").strip()[:2000]
    with Session(db.engine) as s:
        c = _candidate_or_404(s, cid)
        allowed = DECISION_STATUS if c.status in DECIDABLE else ("second_review",) if c.status in FINAL else ()
        if action in DECISION_STATUS and action not in allowed:
            return _panel(request, c, _decision(s, cid), 409, "Decisão indisponível neste status.")
        if action not in DECISION_STATUS:
            return _panel(request, c, _decision(s, cid), 422, "Escolha uma decisão.")
        if action == "reject" and not comment:
            return _panel(request, c, _decision(s, cid), 422, "Comentário obrigatório para reprovar.")
        # the ONLY place a decision is written, always by the recruiter (REQ-L-03)
        s.add(AuditLog(candidate_id=cid, actor="recruiter", action=action, payload_json=json.dumps({"comment": comment}, ensure_ascii=False)))
        c.status = DECISION_STATUS[action]
        s.add(c)
        s.commit()
        s.refresh(c)
        resp = _panel(request, c, _decision(s, cid))
        resp.headers["HX-Refresh"] = "true"  # header shows the real name after a decision (UI-12)
        return resp


@app.get("/candidate/{cid}/report.pdf")
def report_pdf(cid: int):
    with Session(db.engine) as s:
        c = _candidate_or_404(s, cid)
        ev = _evaluation(s, cid)
        if ev is None:
            raise StarletteHTTPException(404)
        pdf = report.render_pdf(c, json.loads(ev.result_json), _decision(s, cid))
    return Response(pdf, media_type="application/pdf")


@app.post("/api/evaluate")
async def api_evaluate(request: Request):
    """Langflow entry (SPEC §7): text in, §6 result out. No candidate rows; evaluate_text anonymizes."""
    try:
        body = await request.json()
    except ValueError:
        body = None
    text = body.get("text") if isinstance(body, dict) else None
    if not isinstance(text, str) or not text.strip():
        return JSONResponse({"detail": "text is required"}, status_code=422)
    form, known = body.get("form") or {}, body.get("known") or {}
    if not isinstance(form, dict) or not isinstance(known, dict):
        return JSONResponse({"detail": "form and known must be objects"}, status_code=422)
    result, _, _ = await run_in_threadpool(
        pipeline.evaluate_text, text, [{"start": 0, "end": 0, "text": text}], form, known)
    with Session(db.engine) as s:  # L-05: every evaluation is audited, also the stateless API one
        s.add(AuditLog(candidate_id=None, actor="system", action="evaluated_api",
                       payload_json=json.dumps({"human_review": result["human_review"], "reasons": result["reasons"]})))
        s.commit()
    return JSONResponse(result)


@app.get("/api/candidates/{cid}")
def api_candidate(cid: int):
    with Session(db.engine) as s:
        ev = _evaluation(s, cid)
        if ev is None:
            raise StarletteHTTPException(404)
        return JSONResponse(json.loads(ev.result_json))
