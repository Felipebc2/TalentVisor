"""Three-layer LLM router (constraints, scoring, cascade) with router_log.

REQ-F-11. Rules: docs/architecture/models-router.md
"""
import os
import time
from typing import NamedTuple

import openai
from sqlmodel import Session

from talentvisor import db, llm

M5_FALLBACK = "gemini-3.5-flash-lite"  # D-018: same family as M5
COOLDOWN_S = 60
MAX_429_WAITS = 3  # 3 judge calls of ~4k tokens don't fit one 8k-TPM minute
MAX_WAIT_S = 65  # Groq free tier resets TPM per minute; one judge call is ~half the 8k TPM, so wait it out
_cooldown: dict[str, float] = {}  # model -> monotonic time until which it is skipped
_REL = {  # relevance 0-10 per slot (M3/M4/M5/M5F) x stage
    "M3": {"E3": 9, "E4": 6, "E6": 5},  # E5 (report) is folded into E4: no separate call
    "M4": {"E3": 7, "E4": 9, "E6": 7},
    "M5": {"E3": 7, "E4": 8, "E6": 9},
    "M6": {"E3": 6, "E4": 7, "E6": 8},  # D-055: backup, third family
}


class Choice(NamedTuple):
    model: str
    reason: str


class NoModelAvailable(Exception):
    """No eligible model (PII, cooldown, window) or every attempt failed."""


def family(model: str) -> str:
    return {"gemini": "gemini", "mistral": "mistral"}.get(llm.provider(model), "gpt-oss")


def _window(model: str) -> int:
    return 1_000_000 if family(model) == "gemini" else 128_000  # gpt-oss and ministral-14b: 128k


def _slots() -> list[tuple[str, str, int]]:
    """(slot, model id, relevance penalty), ids read from env at call time."""
    return [
        ("M3", os.environ.get("M3_MODEL", "openai/gpt-oss-20b"), 0),
        ("M4", os.environ.get("M4_MODEL", "openai/gpt-oss-120b"), 0),
        ("M5", os.environ.get("M5_MODEL", "gemini-4-hydrogen"), 0),
        ("M5", M5_FALLBACK, 1),
        ("M6", os.environ.get("M6_MODEL", "mistral:ministral-14b-2512"), 0),
    ]


def route(stage: str, ctx: dict) -> list[Choice]:
    """Ordered candidates, best first. Empty list: caller must not call any LLM."""
    if ctx.get("has_pii"):  # layer 1: every model is cloud, none is eligible
        return []
    tokens, hard = ctx.get("tokens", 0), ctx.get("complex") or ctx.get("low_audio")
    now, real = time.monotonic(), os.environ.get("LLM_MODE") != "mock"
    scored = []
    for slot, model, pen in _slots():
        if tokens > _window(model) or _cooldown.get(model, 0) > now or (real and not llm.has_key(model)):
            continue
        if stage == "E6" and family(model) in ctx.get("judge_families", {"gpt-oss"}):
            continue
        rel = _REL[slot][stage] - pen
        parts, score = [f"rel {rel}"], rel
        for on, bonus, label in [
            (tokens < 2000 and slot == "M3", 2, "short"),
            (tokens > 8000 and slot == "M5", 2, "long"),
            (hard and slot in ("M4", "M5"), 2, "hard"),
            (ctx.get("demo") and family(model) == "gpt-oss", 1, "demo"),
        ]:
            if on:
                score += bonus
                parts.append(f"+{bonus} {label}")
        # ponytail: no quota signal (no quota data); add -3 when remaining < 20% once available.
        scored.append((score, rel, model, " ".join(parts)))
    scored.sort(key=lambda t: (-t[0], -t[1]))  # ties: higher relevance, then slot order
    return [Choice(m, r) for _, _, m, r in scored]


def call(stage: str, ctx: dict, messages: list[dict], schema, known: dict, *,
         candidate_id: int | None = None, temperature: float = 0.0, seed: int | None = None,
         mock: dict | None = None):
    """Try candidates in order; log every attempt. PIILeakError propagates (fail closed)."""
    prev = None
    for choice in route(stage, ctx):
        waits = 0
        while True:  # retry the same model after short 429 waits (TPM buckets refill each minute)
            row = db.RouterLog(candidate_id=candidate_id, stage=stage, model=choice.model,
                               reason=choice.reason, fallback_from=prev, ok=False)
            t0 = time.monotonic()
            delay = None
            try:
                obj, meta = llm.complete(choice.model, messages, schema, known,
                                         temperature=temperature, seed=seed, mock=mock)
                row.ok, row.tokens = True, meta.get("tokens", 0)
                return obj, meta
            except llm.LLMInvalidOutput:  # ponytail: tokens spent on invalid attempts are logged as 0
                pass  # escalate
            except openai.BadRequestError:  # request-specific (e.g. provider-side schema validation)
                pass  # escalate, no cooldown
            except openai.RateLimitError as e:
                delay = _retry_after(e)
                if waits >= MAX_429_WAITS or delay > MAX_WAIT_S:
                    _cooldown[choice.model] = time.monotonic() + COOLDOWN_S
                    delay = None
            except openai.APIError:  # timeouts, connection errors, 5xx
                _cooldown[choice.model] = time.monotonic() + COOLDOWN_S
            finally:
                row.ms = int((time.monotonic() - t0) * 1000)
                with Session(db.engine) as s:
                    s.add(row)
                    s.commit()
            if delay is None:
                break
            time.sleep(delay)
            waits += 1
        prev = choice.model
    raise NoModelAvailable(f"no model available for {stage}")


def _retry_after(e: openai.RateLimitError) -> float:
    try:
        delay = float(e.response.headers.get("retry-after"))
        return delay if 0 <= delay <= 3600 else 10.0  # nan/negative/absurd → default
    except (TypeError, ValueError):
        # Mistral sends no retry-after but has a per-minute request bucket: 3 x 30 s spans a full window (D-055)
        return 30.0 if "x-ratelimit-remaining-req-minute" in e.response.headers else 10.0
