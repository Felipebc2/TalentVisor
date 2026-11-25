"""OpenAI-compatible client for Groq and Gemini: mock mode, cache, JSON-schema validation, anti-PII assert.

REQ-F-08, REQ-L-04
"""

import hashlib
import json
import os
import time
from functools import cache

import openai
from pydantic import BaseModel, ValidationError
from sqlmodel import Session

from talentvisor import db
from talentvisor.privacy import leaks_known_pii

_PROVIDERS = {
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY"),
}


class PIILeakError(Exception):
    """Known PII found in the prompt; no call was made."""


class LLMInvalidOutput(Exception):
    """Model returned invalid JSON/schema twice; the router should cascade."""


@cache
def _client_for(provider: str) -> openai.OpenAI:
    url, key_env = _PROVIDERS[provider]
    # No SDK retries: the router owns retry/cascade (cooldown on 429/5xx).
    return openai.OpenAI(base_url=url, api_key=os.environ.get(key_env, ""), max_retries=0, timeout=60)


def _client(model: str) -> openai.OpenAI:
    return _client_for("gemini" if model.startswith("gemini") else "groq")


def complete(model: str, messages: list[dict], schema: type[BaseModel], known: dict, *,
             temperature: float = 0.0, seed: int | None = None, mock: dict | None = None) -> tuple[BaseModel, dict]:
    """Return (validated object, meta {ms, tokens, cached, model})."""
    # Anti-PII first: before cache, mock or network.
    if leaks_known_pii(" ".join(str(m.get("content", "")) for m in messages), known):
        raise PIILeakError("known PII found in prompt; call aborted")

    meta = {"ms": 0, "tokens": 0, "cached": False, "model": model}
    if os.environ.get("LLM_MODE") == "mock":
        if mock is None:
            raise ValueError("LLM_MODE=mock but no mock payload given")
        return schema.model_validate(mock), meta

    key = hashlib.sha256(json.dumps([model, messages, temperature, seed], sort_keys=True).encode()).hexdigest()
    with Session(db.engine) as s:
        if hit := s.get(db.LLMCache, key):
            return schema.model_validate_json(hit.response), {**meta, "cached": True}

    msgs, t0 = list(messages), time.monotonic()
    # Gemini's OpenAI-compat endpoint answers 400 to any `seed` (even null); Groq needs it to vary judge runs.
    extra = {"seed": seed} if seed is not None and not model.startswith("gemini") else {}
    for attempt in (1, 2):
        resp = _client(model).chat.completions.create(
            model=model, messages=msgs, temperature=temperature, **extra,
            response_format={"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": schema.model_json_schema()}},
        )
        raw = resp.choices[0].message.content or ""
        meta["tokens"] += resp.usage.total_tokens if resp.usage else 0
        try:
            obj = schema.model_validate_json(raw)
            break
        except ValidationError as e:  # also covers invalid JSON
            if attempt == 2:
                raise LLMInvalidOutput(f"{model}: invalid output after retry") from e
            msgs += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": f"Invalid output, return only JSON matching the schema. Error: {e}"}]
    meta["ms"] = int((time.monotonic() - t0) * 1000)
    with Session(db.engine) as s:
        s.merge(db.LLMCache(key=key, response=raw))
        s.commit()
    return obj, meta


def guard(text: str, known: dict) -> float | None:
    """Max prompt-injection probability from Groq Prompt Guard over ~1500-char chunks; None in mock mode."""
    if leaks_known_pii(text, known):
        raise PIILeakError("known PII found in prompt; call aborted")
    if os.environ.get("LLM_MODE") == "mock":
        return None
    model = os.environ.get("PROMPT_GUARD_MODEL", "meta-llama/llama-prompt-guard-2-86m")
    scores = []
    for i in range(0, max(len(text), 1), 1500):
        resp = _client(model).chat.completions.create(model=model, messages=[{"role": "user", "content": text[i:i + 1500]}])
        raw = (resp.choices[0].message.content or "").strip().upper()
        score = {"MALICIOUS": 1.0, "BENIGN": 0.0}.get(raw) if raw in ("MALICIOUS", "BENIGN") else float(raw)
        if not 0 <= score <= 1:  # NaN or out of range would fail open through max()
            raise ValueError("unexpected prompt-guard reply")
        scores.append(score)
    return max(scores)
