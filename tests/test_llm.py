from types import SimpleNamespace

import pytest
from pydantic import BaseModel
from sqlmodel import create_engine

from talentvisor import llm

KNOWN = {"name": "Maria Souza"}


class Out(BaseModel):
    score: int


class Fake:
    """Stands in for openai.OpenAI; replies are consumed in order."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kw):
        self.calls.append(kw["messages"][:])
        msg = SimpleNamespace(content=self.replies.pop(0))
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=SimpleNamespace(total_tokens=7))


@pytest.fixture
def real(tmp_path, monkeypatch):
    from talentvisor import db

    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))
    db.init_db()
    monkeypatch.setenv("LLM_MODE", "real")

    def use(fake):
        monkeypatch.setattr(llm, "_client", lambda model: fake)
        return fake

    return use


MSGS = [{"role": "user", "content": "rate this answer"}]


def test_aborts_on_pii(real, monkeypatch):
    fake = real(Fake('{"score": 1}'))
    for mode in ("real", "mock"):
        monkeypatch.setenv("LLM_MODE", mode)
        with pytest.raises(llm.PIILeakError) as e:
            llm.complete("m", [{"role": "user", "content": "answer by Maria Souza"}], Out, KNOWN, mock={"score": 1})
        assert "Maria" not in str(e.value)
    assert fake.calls == []


def test_mock_and_cache(real, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    obj, meta = llm.complete("m", MSGS, Out, KNOWN, mock={"score": 3})
    assert obj.score == 3 and not meta["cached"]
    with pytest.raises(ValueError):
        llm.complete("m", MSGS, Out, KNOWN)

    monkeypatch.setenv("LLM_MODE", "real")
    fake = real(Fake('{"score": 4}'))
    obj, meta = llm.complete("m", MSGS, Out, KNOWN)
    assert obj.score == 4 and not meta["cached"] and meta["tokens"] == 7
    obj, meta = llm.complete("m", MSGS, Out, KNOWN)
    assert obj.score == 4 and meta["cached"] and meta["ms"] == 0
    assert len(fake.calls) == 1


def test_retry_on_invalid_json(real):
    fake = real(Fake("not json", '{"score": 2}'))
    obj, _ = llm.complete("m", MSGS, Out, KNOWN)
    assert obj.score == 2 and len(fake.calls) == 2
    assert fake.calls[1][-2:][0] == {"role": "assistant", "content": "not json"}
    assert "Error" in fake.calls[1][-1]["content"]


def test_invalid_twice_raises(real):
    fake = real(Fake("nope", '{"score": "x"}'))
    with pytest.raises(llm.LLMInvalidOutput):
        llm.complete("m", MSGS, Out, KNOWN)
    assert len(fake.calls) == 2


def test_guard_mock_returns_none(real, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "mock")
    assert llm.guard("texto qualquer", KNOWN) is None


def test_guard_aborts_on_pii(real, monkeypatch):
    fake = real(Fake("0.1"))
    for mode in ("real", "mock"):
        monkeypatch.setenv("LLM_MODE", mode)
        with pytest.raises(llm.PIILeakError):
            llm.guard("answer by Maria Souza", KNOWN)
    assert fake.calls == []


def test_guard_max_over_chunks(real):
    fake = real(Fake("0.1", "0.97", "BENIGN"))
    assert llm.guard("a" * 3200, KNOWN) == 0.97
    assert len(fake.calls) == 3


def test_guard_bad_reply_raises(real):
    # NaN or out of range would fail open through max(); text is not a score
    for reply in ("nan", "NaN", "1.5", "-0.1", "inf", "probably safe", ""):
        real(Fake(reply))
        with pytest.raises(ValueError):
            llm.guard("texto qualquer", KNOWN)


def test_seed_not_sent_to_gemini(monkeypatch, tmp_path):
    """Gemini OpenAI-compat rejects `seed` with 400; Groq gets it."""
    from types import SimpleNamespace

    from pydantic import BaseModel
    from sqlmodel import create_engine

    from talentvisor import db, llm

    class Out(BaseModel):
        ok: bool

    monkeypatch.setattr(db, "engine", create_engine(f"sqlite:///{tmp_path}/t.db"))
    db.init_db()
    monkeypatch.setenv("LLM_MODE", "real")
    seen = []

    def create(**kw):
        seen.append(kw)
        msg = SimpleNamespace(content='{"ok": true}')
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)], usage=None)

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, "_client", lambda model: fake)
    llm.complete("gemini-3.5-flash-lite", [{"role": "user", "content": "x"}], Out, {}, seed=1)
    llm.complete("openai/gpt-oss-120b", [{"role": "user", "content": "x"}], Out, {}, seed=1)
    llm.complete("mistral:ministral-14b-2512", [{"role": "user", "content": "x"}], Out, {}, seed=1)
    assert "seed" not in seen[0] and seen[1]["seed"] == 1
    assert "seed" not in seen[2] and seen[2]["model"] == "ministral-14b-2512"  # prefix stripped (D-055)
    assert seen[1]["model"] == "openai/gpt-oss-120b" and llm.provider("mistral:x") == "mistral"
