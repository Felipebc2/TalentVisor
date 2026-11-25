import importlib.util
import json
from pathlib import Path

from sqlmodel import create_engine

ROOT = Path(__file__).parent.parent


def test_fixture_structure():
    cases = json.loads((ROOT / "tests/fixtures/synthetic.json").read_text(encoding="utf-8"))
    assert [c["label"] for c in cases] == ["excellent", "average", "poor", "informal", "injection"]
    for c in cases:
        assert {"id", "label", "known", "transcript", "form"} <= c.keys()
        assert c["known"]["name"] in c["transcript"] and set(c["form"]["answers"]) == {"P01", "P02", "P03", "P04", "P05"}


def test_eval_mock_flags_injection(tmp_path, monkeypatch, capsys):
    from talentvisor import db

    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))
    monkeypatch.setenv("LLM_MODE", "mock")
    spec = importlib.util.spec_from_file_location("eval_script", ROOT / "scripts/eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.main() == 0
    out = capsys.readouterr().out
    assert "ordering checks skipped" in out and "injection_detected" in out
    assert "anon mean precision=" in out and "recall=" in out


def test_eval_provider_error_inconclusive(tmp_path, monkeypatch, capsys):
    from talentvisor import db, pipeline, router

    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))
    monkeypatch.setenv("LLM_MODE", "mock")
    spec = importlib.util.spec_from_file_location("eval_script", ROOT / "scripts/eval.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    real = pipeline.evaluate_text

    def flaky(*a, candidate_code=None, **k):
        if candidate_code == "poor":
            raise router.NoModelAvailable("down")
        return real(*a, candidate_code=candidate_code, **k)

    monkeypatch.setattr(pipeline, "evaluate_text", flaky)
    assert mod.main() == 2
    assert "poor       inconclusive" in capsys.readouterr().out
