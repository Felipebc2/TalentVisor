import csv
import importlib.util
import io
import zipfile
from pathlib import Path

import pytest
from sqlmodel import Session, create_engine, select

SPEC = importlib.util.spec_from_file_location("import_dataset", Path(__file__).parent.parent / "scripts/import_dataset.py")


def _csv(header, rows):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(header)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


@pytest.fixture
def env(tmp_path, monkeypatch):
    from talentvisor import db, pipeline

    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))
    calls = []
    monkeypatch.setattr(pipeline, "run", calls.append)
    mod = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(mod)
    monkeypatch.setattr(mod, "UPLOAD_DIR", tmp_path / "up")
    cands = [(i, f"Fulana {i}", "Sim" if lib == "Sim" else lib, f"{i}_video.mp4") for i, lib in
             [("X001", "Sim"), ("X002", "Não"), ("X003", " Sim ")]]
    z = tmp_path / "ds.zip"
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("csv/candidatos.csv", _csv(
            ["id_candidato", "nome_pseudonimo", "formacao_direito", "experiencia_resumida", "arquivo_video", "liberado_analise"],
            [(i, n, "Graduação", "Estágio", v, lib) for i, n, lib, v in cands]))
        zf.writestr("csv/respostas.csv", _csv(
            ["id_candidato", "id_pergunta", "resposta_escrita"],
            [(i, p, f"fake {p}") for i, *_ in cands for p in ("P01", "P02")]))
        for *_, v in cands:
            zf.writestr(f"videos/{v}", b"dummy")
    return db, mod, calls, z, tmp_path


def test_c002_refused(env):
    db, mod, calls, z, tmp = env
    mod.main(str(z))
    with Session(db.engine) as s:
        cands = s.exec(select(db.Candidate)).all()
        audits = s.exec(select(db.AuditLog)).all()
    ok = [c for c in cands if c.cleared]
    assert len(cands) == 3 and len(ok) == 2 and all(c.consent_version == "dataset" for c in ok)
    assert sorted(c.real_name for c in ok) == ["Fulana X001", "Fulana X003"]
    ref = next(c for c in cands if c.status == "refused")
    assert (ref.cleared, ref.real_name, ref.pii_json, ref.form_json, ref.video_path) == (False, None, "{}", "{}", None)
    assert [(a.action, a.candidate_id) for a in audits if "X002" in a.payload_json] == [("refused", ref.id)]
    assert len(calls) == 2 and ref.id not in calls
    files = list((tmp / "up").glob("*.mp4"))
    assert len(files) == 2 and {Path(c.video_path) for c in ok} == set(files)


def test_idempotent(env):
    db, mod, calls, z, _ = env
    mod.main(str(z))
    mod.main(str(z))
    with Session(db.engine) as s:
        assert len(s.exec(select(db.Candidate)).all()) == 3
    assert len(calls) == 2


def test_missing_video_skipped_and_dashboard(env, capsys):
    import zipfile as zf_

    from fastapi.testclient import TestClient

    db, mod, calls, z, tmp = env
    # rebuild the zip without X001's video: X001 is skipped, X003 still imports
    z2 = tmp / "ds2.zip"
    with zf_.ZipFile(z) as src, zf_.ZipFile(z2, "w") as dst:
        for n in src.namelist():
            if "X001_video" not in n:
                dst.writestr(n, src.read(n))
    mod.main(str(z2))
    assert "X001: skipped: KeyError" in capsys.readouterr().out
    with Session(db.engine) as s:
        assert sorted(c.status for c in s.exec(select(db.Candidate)).all()) == ["received", "refused"]
    assert len(calls) == 1
    from talentvisor.app import app
    assert "recusado" in TestClient(app).get("/dashboard").text


def test_error_row_is_retried(env):
    db, mod, calls, z, _ = env
    mod.main(str(z))
    with Session(db.engine) as s:
        c = s.get(db.Candidate, calls[0])
        c.status = "error"
        s.add(c)
        s.commit()
    mod.main(str(z))
    assert len(calls) == 3  # only the errored row runs again; refused and evaluated rows are skipped
    with Session(db.engine) as s:
        assert len(s.exec(select(db.Candidate)).all()) == 4
