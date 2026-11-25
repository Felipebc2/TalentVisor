"""FastAPI routes: candidate pages, recruiter dashboard, decision, PDF, JSON API and /health.

REQ-F-01, REQ-F-02, REQ-F-14..17, REQ-NF-03, REQ-NF-04, REQ-NF-06. UI: docs/spec/ui.md
"""

import os
import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="TalentVisor")

DB_PATH = Path("data/talentvisor.db")


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
