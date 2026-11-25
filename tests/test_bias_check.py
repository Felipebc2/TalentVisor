import importlib.util
import json
from pathlib import Path

from sqlmodel import create_engine

ROOT = Path(__file__).parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("bias_script", ROOT / "scripts/bias_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_gender_swap_map():
    mod = _load()
    assert mod.swap_gender("Ele é formado e ela é advogada, dele e dela.") == "Ela é formada e ele é advogado, dela e dele."


def test_swap_name_parts_and_caps():
    mod = _load()
    out = mod.swap_name("Sou Camila. Torres e CAMILA.", "Camila Torres Andrade", "João Pereira Lima")
    assert "Camila" not in out and "Torres" not in out and out.startswith("Sou João.")
    assert mod.swap_gender("ELE e Ela") == "ELA e Ele"


def test_bias_check_mock(tmp_path, monkeypatch, capsys):
    from talentvisor import db

    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))
    monkeypatch.setenv("LLM_MODE", "mock")
    mod = _load()
    cases = json.loads(mod.FIXTURE.read_text(encoding="utf-8"))
    vs = mod.variants(cases)
    assert len(vs) >= 3
    assert all(b["known"]["name"] not in v["transcript"] for n, b, v in vs if "gender" in n)
    assert mod.main() == 0
    assert "Δ is 0 by construction" in capsys.readouterr().out


def test_bias_check_provider_error_inconclusive(tmp_path, monkeypatch, capsys):
    from talentvisor import db, pipeline, router

    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))
    monkeypatch.setenv("LLM_MODE", "mock")
    mod = _load()

    def down(*a, **k):
        raise router.NoModelAvailable("down")

    monkeypatch.setattr(pipeline, "evaluate_text", down)
    assert mod.main() == 2
    assert "inconclusive: NoModelAvailable" in capsys.readouterr().out
