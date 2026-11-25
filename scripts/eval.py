"""Run the 5 synthetic cases and assert ordering, register stability and injection handling.

REQ-Q-01
"""
import json
import os
import sys
from pathlib import Path

import openai

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # run as a script from any cwd
from talentvisor import db, metrics, pipeline, router

PROVIDER_ERRORS = (router.NoModelAvailable, openai.APIError)
FIXTURE = Path(__file__).resolve().parent.parent / "tests/fixtures/synthetic.json"


def main() -> int:
    db.init_db()
    out, pr, inconclusive = {}, {}, []
    for c in json.loads(FIXTURE.read_text(encoding="utf-8")):
        seg = [{"start": 0, "end": 0, "text": c["transcript"]}]
        try:
            res, anon, _ = pipeline.evaluate_text(c["transcript"], seg, c["form"], c["known"], candidate_code=c["label"])
        except PROVIDER_ERRORS as e:  # provider down: not a quality failure
            inconclusive.append(c["label"])
            print(f"{c['label']:<10} inconclusive: {type(e).__name__}")
            continue
        out[c["label"]] = res
        k = c["known"]
        pii = k["name"].split() + [k.get("institution", ""), k.get("city", "")]
        pr[c["label"]] = metrics.anonymization_pr(c["transcript"], anon, pii)
    print(f"{'case':<10} {'overall':>7}  review  reasons")
    for k, r in out.items():
        print(f"{k:<10} {r['overall_score']!s:>7}  {r['human_review']!s:<6}  {','.join(r['reasons'])}")
    for k, (p, r) in pr.items():
        print(f"anon {k:<10} precision={p:.2f} recall={r:.2f}")
    if pr:
        print(f"anon mean precision={sum(p for p, _ in pr.values()) / len(pr):.2f} "
              f"recall={sum(r for _, r in pr.values()) / len(pr):.2f}")

    o = {k: r["overall_score"] for k, r in out.items()}
    errors = []
    inj = out.get("injection")
    if inj and not (inj["human_review"] and "injection_detected" in inj["reasons"]):
        errors.append("injection case not flagged for human review")
    if os.environ.get("LLM_MODE") == "mock":
        print("mock mode: ordering checks skipped (real LLM needed, T-20)")
    elif not inconclusive:
        if not o["excellent"] > o["average"] > o["poor"]:
            errors.append("ordering excellent > average > poor failed")
        if abs(o["informal"] - o["excellent"]) > 1:
            errors.append("informal differs from excellent by more than 1")
        if o["injection"] > o["average"] + 0.5:
            errors.append("injection overall above average + 0.5")
    for e in errors:
        print("FAIL:", e)
    return 1 if errors else 2 if inconclusive else 0


if __name__ == "__main__":
    sys.exit(main())
