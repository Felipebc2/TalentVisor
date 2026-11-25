import httpx
import openai
import pytest
from pydantic import BaseModel
from sqlmodel import Session, create_engine, select

from talentvisor import db, llm, router

SLEPT = []


class Out(BaseModel):
    x: int = 1


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(router.time, "sleep", lambda s: SLEPT.append(s))
    SLEPT.clear()
    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))
    db.init_db()
    router._cooldown.clear()
    for k in ("M3_MODEL", "M4_MODEL", "M5_MODEL"):
        monkeypatch.delenv(k, raising=False)
    yield
    router._cooldown.clear()


def api_err(cls, status, **headers):
    req = httpx.Request("POST", "http://x")
    return cls(str(status), response=httpx.Response(status, headers=headers, request=req), body=None)


def rate_limit(**headers):  # default: long retry-after, i.e. straight to cooldown
    return api_err(openai.RateLimitError, 429, **(headers or {"retry-after": "120"}))


def fake(monkeypatch, fail=None):
    """fail: {model: exception}; returns the list of models called."""
    calls = []

    def complete(model, messages, schema, known, **kw):
        calls.append(model)
        if model in (fail or {}):
            raise fail[model]
        return Out(), {"ms": 1, "tokens": 5, "cached": False, "model": model}

    monkeypatch.setattr(llm, "complete", complete)
    return calls


def logs():
    with Session(db.engine) as s:
        return s.exec(select(db.RouterLog).order_by(db.RouterLog.id)).all()


def test_pii_routes_nowhere(monkeypatch):
    calls = fake(monkeypatch)
    assert router.route("E4", {"has_pii": True}) == []
    with pytest.raises(router.NoModelAvailable):
        router.call("E4", {"has_pii": True}, [], Out, {})
    assert calls == []


def test_429_falls_back_to_m5(monkeypatch):
    calls = fake(monkeypatch, {"openai/gpt-oss-120b": rate_limit()})
    _, meta = router.call("E4", {"tokens": 3000}, [], Out, {}, candidate_id=7)
    assert calls == ["openai/gpt-oss-120b", "gemini-4-hydrogen"]
    a, b = logs()
    assert (a.model, a.ok, a.candidate_id) == ("openai/gpt-oss-120b", False, 7)
    assert (b.model, b.ok, b.fallback_from, b.tokens) == ("gemini-4-hydrogen", True, "openai/gpt-oss-120b", 5)
    assert "openai/gpt-oss-120b" not in [c.model for c in router.route("E4", {})]  # cooldown


def test_e6_other_family():
    assert {router.family(c.model) for c in router.route("E6", {})} == {"gemini"}
    assert {router.family(c.model) for c in router.route("E6", {"judge_family": "gemini"})} == {"gpt-oss"}


def test_invalid_output_escalates(monkeypatch):
    calls = fake(monkeypatch, {"openai/gpt-oss-20b": llm.LLMInvalidOutput()})
    router.call("E3", {"tokens": 500}, [], Out, {})
    assert calls == ["openai/gpt-oss-20b", "openai/gpt-oss-120b"]
    assert [r.ok for r in logs()] == [False, True]
    assert router._cooldown == {}  # invalid output is not a cooldown


def test_e3_short_prefers_m3():
    assert router.route("E3", {"tokens": 500})[0].model == "openai/gpt-oss-20b"
    assert router.route("E4", {"critical": True})[0].model == "openai/gpt-oss-120b"


def test_e4_short_429_on_m4_goes_to_m5(monkeypatch):
    assert [c.model for c in router.route("E4", {})][:3] == [
        "openai/gpt-oss-120b", "gemini-4-hydrogen", "openai/gpt-oss-20b"]
    calls = fake(monkeypatch, {"openai/gpt-oss-120b": rate_limit()})
    router.call("E4", {}, [], Out, {})
    assert calls == ["openai/gpt-oss-120b", "gemini-4-hydrogen"]


def test_pii_leak_propagates_and_is_logged(monkeypatch):
    fake(monkeypatch, {"openai/gpt-oss-120b": llm.PIILeakError()})
    with pytest.raises(llm.PIILeakError):
        router.call("E4", {}, [], Out, {})
    assert [r.ok for r in logs()] == [False]


def test_429_waits_and_retries_same_model(monkeypatch):
    n = []

    def complete(model, *a, **kw):
        n.append(model)
        if len(n) == 1:
            raise rate_limit(**{"retry-after": "2"})
        return Out(), {"tokens": 5}

    monkeypatch.setattr(llm, "complete", complete)
    router.call("E4", {"tokens": 3000}, [], Out, {})
    assert n == ["openai/gpt-oss-120b"] * 2
    assert SLEPT == [2.0]
    assert [r.ok for r in logs()] == [False, True]
    assert router._cooldown == {}


def test_429_long_retry_after_falls_back(monkeypatch):
    calls = fake(monkeypatch, {"openai/gpt-oss-120b": rate_limit(**{"retry-after": "120"})})
    router.call("E4", {"tokens": 3000}, [], Out, {})
    assert calls == ["openai/gpt-oss-120b", "gemini-4-hydrogen"]
    assert SLEPT == []
    assert "openai/gpt-oss-120b" in router._cooldown


def test_bad_request_no_cooldown(monkeypatch):
    calls = fake(monkeypatch, {"openai/gpt-oss-120b": api_err(openai.BadRequestError, 400)})
    router.call("E4", {"tokens": 3000}, [], Out, {})
    assert calls == ["openai/gpt-oss-120b", "gemini-4-hydrogen"]
    assert router._cooldown == {}
    assert [r.ok for r in logs()] == [False, True]
