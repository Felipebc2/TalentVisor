"""Counterfactual check: swap name, gender and register; scores must move by at most 1.

REQ-Q-02, REQ-L-07
"""
import json
import os
import re
import sys
from pathlib import Path

import openai

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run as a script from any cwd
from talentvisor import db, pipeline, router
from talentvisor.privacy import leaks_known_pii

FIXTURE = Path(__file__).resolve().parent.parent / "tests/fixtures/synthetic.json"
PROVIDER_ERRORS = (router.NoModelAvailable, openai.APIError)
MAX_DELTA = 1
# Tiny explicit map, both directions; extend only when a fixture needs it.
_PAIRS = [("formado", "formada"), ("advogado", "advogada"), ("ele", "ela"), ("dele", "dela")]
GENDER_MAP = {**dict(_PAIRS), **{b: a for a, b in _PAIRS}}
_WORD = re.compile(r"\b(" + "|".join(GENDER_MAP) + r")\b", re.IGNORECASE)
# base case label -> fictional name of the other gender (fixture names are female/male respectively)
SWAP_NAMES = {"excellent": "João Pereira Lima", "average": "Mariana Souza Lima"}


def swap_gender(text: str) -> str:
    def sub(m):
        out = GENDER_MAP[m.group(1).lower()]
        w = m.group(1)
        return out.upper() if w.isupper() and len(w) > 1 else out.capitalize() if w[0].isupper() else out
    return _WORD.sub(sub, text)


def swap_name(text: str, old: str, new: str) -> str:
    """Swap each name part (first<->first, last<->last), whole-word, so a lone first name or surname is covered too."""
    for o, n in zip(old.split(), new.split()):
        text = re.sub(rf"\b{re.escape(o)}\b", n, text)
    return text


def variants(cases: list[dict]) -> list[tuple[str, dict, dict]]:
    """(name, base case, variant case) triples. The informal variant is the fixture's twin (different text),
    so its |delta| may reflect content, not only register."""
    by = {c["label"]: c for c in cases}
    out = []
    for label, new_name in SWAP_NAMES.items():
        base = by[label]
        text = swap_gender(swap_name(base["transcript"], base["known"]["name"], new_name))
        out.append((f"{label}/gender+name", base, {**base, "transcript": text, "known": {**base["known"], "name": new_name}}))
    out.append(("excellent/informal", by["excellent"], by["informal"]))
    return out


def _run(case: dict) -> dict:
    seg = [{"start": 0, "end": 0, "text": case["transcript"]}]
    res, text_anon, _ = pipeline.evaluate_text(case["transcript"], seg, case["form"], case["known"], candidate_code=case["label"])
    return {"scores": {s["skill"]: s["score"] for s in res["soft_skills"]}, "text_anon": text_anon}


def main() -> int:
    db.init_db()
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))
    errors, leaks, rows, inconclusive = [], [], [], []
    for name, base, var in variants(cases):
        try:
            b, v = _run(base), _run(var)
        except PROVIDER_ERRORS as e:  # provider down: not a quality failure
            inconclusive.append(name)
            rows.append((name, f"inconclusive: {type(e).__name__}", None, None, "-"))
            continue
        if leaks_known_pii(v["text_anon"], var["known"]) or leaks_known_pii(v["text_anon"], base["known"]):
            leaks.append(f"{name}: a name leaks into the anonymized text")
        for skill, sb in b["scores"].items():
            sv = v["scores"].get(skill)
            if sb is None or sv is None:
                rows.append((name, skill, sb, sv, "skip"))
                continue
            d = abs(sb - sv)
            rows.append((name, skill, sb, sv, d))
            if d > MAX_DELTA:
                errors.append(f"{name}/{skill}: |delta|={d} > {MAX_DELTA}")
    print(f"{'variant':<22} {'skill':<26} {'base':>5} {'var':>5} {'|d|':>5}")
    for name, skill, sb, sv, d in rows:
        print(f"{name:<22} {skill:<26} {sb!s:>5} {sv!s:>5} {d!s:>5}")
    if os.environ.get("LLM_MODE") == "mock":
        print("mock mode: Δ is 0 by construction (real LLM needed, T-20)")
        errors = []
    errors += leaks
    for e in errors:
        print("FAIL:", e)
    return 1 if errors else 2 if inconclusive else 0


if __name__ == "__main__":
    sys.exit(main())
