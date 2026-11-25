"""Import the research dataset (zip or dir); refuses candidates not cleared for analysis.

REQ-F-03, REQ-L-06. Dataset: docs/domain/dataset.md
"""
import csv
import io
import json
import os
import secrets
import shutil
import sys
import uuid
import zipfile
from pathlib import Path

from sqlmodel import Session, select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run as a script from any cwd
from talentvisor import db, pipeline  # noqa: E402

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "data/uploads"))


class Source:
    """Read-only view over a dataset zip or directory (same layout)."""

    def __init__(self, path: Path):
        self.zip = zipfile.ZipFile(path) if path.is_file() else None
        self.root = path

    def rows(self, name: str) -> list[dict]:
        raw = self.zip.read(name) if self.zip else (self.root / name).read_bytes()
        return list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig")), delimiter=";"))

    def copy_video(self, name: str, dest: Path) -> None:
        name = f"videos/{Path(name).name}"
        src = self.zip.open(name) if self.zip else (self.root / name).open("rb")  # missing video fails before dest exists
        with src as f, dest.open("wb") as out:
            shutil.copyfileobj(f, out)


def _audit(s: Session, action: str, dataset_id: str, candidate_id: int | None = None) -> None:
    s.add(db.AuditLog(candidate_id=candidate_id, actor="system", action=action,
                      payload_json=json.dumps({"dataset_id": dataset_id})))


def main(path: str) -> None:
    db.init_db()
    src = Source(Path(path))
    answers: dict[str, dict[str, str]] = {}
    for r in src.rows("csv/respostas.csv"):
        answers.setdefault(r["id_candidato"], {})[r["id_pergunta"]] = r["resposta_escrita"]
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    for row in src.rows("csv/candidatos.csv"):
        did = row["id_candidato"]
        try:
            cid = _import_row(src, row, answers, did)
        except Exception as e:  # one bad row (e.g. missing video) must not stop the import
            print(f"{did}: skipped: {type(e).__name__}")
            continue
        if cid is None:
            continue
        pipeline.run(cid)
        with Session(db.engine) as s:
            c = s.get(db.Candidate, cid)
            print(f"{did} -> {c.code} -> {c.status}")


def _new_code(s: Session) -> str:
    while True:
        code = f"TV-{secrets.token_hex(2).upper()}"
        if not s.exec(select(db.Candidate).where(db.Candidate.code == code)).first():
            return code


def _import_row(src: Source, row: dict, answers: dict, did: str) -> int | None:
    """Create the candidate (and audit); return its id to process, or None when nothing to run."""
    marker = json.dumps({"dataset_id": did})
    with Session(db.engine) as s:
        done = s.exec(select(db.AuditLog).where(db.AuditLog.action.in_(["imported", "refused"]),
                                                db.AuditLog.payload_json == marker)).first()
        if done:
            print(f"{did}: skipped: already imported")
            return None
        if (row["liberado_analise"] or "").strip() != "Sim":
            # refused: placeholder row with no PII and no video, never processed
            cand = db.Candidate(code=_new_code(s), status="refused", cleared=False, consent_version="dataset",
                                consent_at=db.now_utc(), real_name=None, pii_json="{}", form_json="{}")
            s.add(cand)
            s.flush()
            _audit(s, "refused", did, cand.id)
            s.commit()
            print(f"{did}: refused: no authorization")
            return None
        video = UPLOAD_DIR / f"{uuid.uuid4()}.mp4"
        src.copy_video(row["arquivo_video"], video)
        name = row["nome_pseudonimo"]
        form = {"education": row["formacao_direito"], "experience": row["experiencia_resumida"],
                "description": "", "answers": answers.get(did, {})}
        try:
            cand = db.Candidate(
                code=_new_code(s), status="received", cleared=True, consent_version="dataset", consent_at=db.now_utc(),
                real_name=name, pii_json=json.dumps({"name": name}), form_json=json.dumps(form),
                video_path=str(video))
            s.add(cand)
            s.flush()
            _audit(s, "imported", did, cand.id)
            s.commit()
        except Exception:
            video.unlink(missing_ok=True)
            raise
        return cand.id


if __name__ == "__main__":
    main(sys.argv[1])
