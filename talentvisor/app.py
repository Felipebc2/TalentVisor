"""FastAPI routes: candidate pages, recruiter dashboard, decision, PDF, JSON API and /health.

REQ-F-01, REQ-F-02, REQ-F-14..17, REQ-NF-03, REQ-NF-04, REQ-NF-06. UI: docs/spec/ui.md
"""

import csv
import io
import json
import os
import secrets
import shutil
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select
from starlette.exceptions import HTTPException as StarletteHTTPException

from talentvisor import db
from talentvisor.db import AuditLog, Candidate, now_utc

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=BASE / "templates")  # autoescape on for .html

CONSENT_VERSION = "v1"
MAX_BYTES = 300 * 1024 * 1024
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "data/uploads"))
VIDEO_TYPES = {".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime"}
FLASH = {"consent": "Aceite o termo para continuar."}  # fixed texts: never echo user input
QUESTIONS = [
    ("P01", "Como você explicaria a um cliente, sem formação jurídica, um assunto de Direito que ele não compreendeu?"),
    ("P02", "Imagine que dois colegas discordam sobre como conduzir uma tarefa. Como você ajudaria a resolver a situação?"),
    ("P03", "Você recebeu três demandas urgentes com prazos próximos. Como decidiria por onde começar?"),
    ("P04", "Um cliente demonstra insatisfação e interrompe sua explicação. Como você conduziria a conversa?"),
    ("P05", "Você percebeu um erro em um documento que já foi enviado para revisão. O que faria?"),
]
CSV_MAP = {"nome_pseudonimo": "name", "formacao_direito": "education", "experiencia_resumida": "experience"}
TEXT_FIELDS = ("name", "institution", "city", "education", "experience", "description")


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    db.purge_expired()
    yield


app = FastAPI(title="TalentVisor", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

DB_PATH = Path("data/talentvisor.db")


def render(request: Request, name: str, status: int = 200, **ctx):
    return templates.TemplateResponse(request, name, {"flash": FLASH.get(request.query_params.get("msg")), **ctx}, status_code=status)


def error_page(request: Request, status: int, message: str):
    return render(request, "error.html", status, status_code=status, message=message)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    msg = "Página não encontrada." if exc.status_code == 404 else "Requisição inválida."
    return error_page(request, exc.status_code, msg)


@app.exception_handler(Exception)
async def server_error(request: Request, exc: Exception):
    return error_page(request, 500, "Algo deu errado. Tente novamente em instantes.")


def _db_ok() -> bool:
    try:
        DB_PATH.parent.mkdir(exist_ok=True)
        with sqlite3.connect(DB_PATH) as con:
            return con.execute("select 1").fetchone() == (1,)
    except Exception:
        return False


def _stt_ok() -> bool:
    try:  # local files only: no load, no download
        from faster_whisper.utils import download_model

        download_model(os.environ.get("STT_MODEL", "large-v3-turbo"), local_files_only=True)
        return True
    except Exception:
        return False


@app.get("/health")
def health():
    body = {
        "db": _db_ok(),
        "stt_model": _stt_ok(),
        "keys": {"groq": bool(os.environ.get("GROQ_API_KEY")), "gemini": bool(os.environ.get("GEMINI_API_KEY"))},
    }
    # Missing keys don't fail health: mock mode runs without them (D-025).
    return JSONResponse(body, status_code=200 if body["db"] and body["stt_model"] else 503)


@app.get("/")
def consent(request: Request):
    return render(request, "consent.html", version=CONSENT_VERSION)


def upload_form(request: Request, status: int = 200, values=None, errors=None):
    return render(request, "upload.html", status, questions=QUESTIONS, version=CONSENT_VERSION, v=values or {}, errors=errors or {})


@app.get("/upload")
def upload_page(request: Request, consent: str = ""):
    if consent != CONSENT_VERSION:
        return RedirectResponse("/?msg=consent", status_code=303)
    return upload_form(request)


def _csv_row(raw: bytes) -> dict:
    """First data row of a ';' CSV mapped to form fields (known columns only)."""
    row = next(csv.DictReader(io.StringIO(raw[:100_000].decode("utf-8-sig", "replace")), delimiter=";"), {})
    return {CSV_MAP[k.strip()]: (v or "").strip() for k, v in row.items() if k and k.strip() in CSV_MAP}


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
async def upload(request: Request):
    if int(request.headers.get("content-length") or 0) > MAX_BYTES + 1_000_000:
        return error_page(request, 413, "Arquivo muito grande (máx. 300 MB).")
    form = await request.form()
    if form.get("consent") != CONSENT_VERSION:
        return error_page(request, 400, "É preciso aceitar o termo de consentimento.")
    v = {k: str(form.get(k) or "").strip() for k in TEXT_FIELDS}
    v.update({p: str(form.get(p) or "").strip() for p, _ in QUESTIONS})
    csv_file = form.get("csv")
    if csv_file is not None and getattr(csv_file, "filename", ""):
        v.update({k: x for k, x in _csv_row(await csv_file.read()).items() if x and not v[k]})
    errors = {k: "Campo obrigatório." for k in ("name", "institution", "city", "education") if not v[k]}
    video, path = form.get("video"), None
    if video is None or not getattr(video, "filename", ""):
        errors["video"] = "Envie o vídeo."
    else:
        path, err = _save_video(video)
        if err:
            errors["video"] = err
    if errors:
        if path:
            path.unlink(missing_ok=True)
        return upload_form(request, 400, v, errors)

    form_json = {
        "education": v["education"], "experience": v["experience"], "description": v["description"],
        "answers": {p: v[p] for p, _ in QUESTIONS},
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
            s.add(AuditLog(candidate_id=cand.id, actor="candidate", action="submitted"))
            s.commit()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return RedirectResponse(f"/submitted/{code}", status_code=303)


@app.get("/submitted/{code}")
def submitted(request: Request, code: str):
    with Session(db.engine) as s:
        if not s.exec(select(Candidate).where(Candidate.code == code)).first():
            return error_page(request, 404, "Página não encontrada.")
    return render(request, "submitted.html", code=code)


@app.get("/dashboard")
def dashboard(request: Request):
    with Session(db.engine) as s:
        rows = [
            {"code": c.code, "status": c.status, "sent": c.created_at.strftime("%d/%m %H:%M")}
            for c in s.exec(select(Candidate).order_by(Candidate.created_at.desc()))
        ]
    return render(request, "dashboard.html", rows=rows)
