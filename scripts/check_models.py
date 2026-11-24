"""Smoke-check API keys and model IDs with one tiny call per model. Prints status only, never key values.

Run inside a container so keys come from env_file:
    docker run --rm --env-file .env -v "$PWD/scripts:/s:ro" python:3.14-slim python /s/check_models.py

REQ-NF-03. Models: docs/architecture/models-router.md
"""

import json
import os
import sys
import urllib.error
import urllib.request

GROQ = "https://api.groq.com/openai/v1"
GEMINI = "https://generativelanguage.googleapis.com/v1beta"
SECRETS = [v for v in (os.getenv("GROQ_API_KEY"), os.getenv("GEMINI_API_KEY")) if v]
# Free Gemini alternatives tried when M5_MODEL fails, best first.
GEMINI_FALLBACKS = ["gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash-preview", "gemini-2.5-flash-lite"]


def scrub(text):
    for s in SECRETS:
        text = text.replace(s, "***")
    return " ".join(text.split())[:220]


def call(url, headers, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None, headers={"Content-Type": "application/json", "User-Agent": "talentvisor-check/0.1", **headers})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", {})
            msg = msg.get("message", str(msg)) if isinstance(msg, dict) else str(msg)
        except Exception:
            msg = e.reason
        return e.code, scrub(str(msg))
    except Exception as e:  # network errors
        return 0, scrub(str(e))


def report(name, status, detail=""):
    ok = status == 200
    print(f"{'OK  ' if ok else 'FAIL'} {name:<45} {status} {'' if ok else detail}")
    return ok


def check_groq(key):
    h = {"Authorization": f"Bearer {key}"}
    status, data = call(f"{GROQ}/models", h)
    if not report("groq: list models", status, data):
        return False
    ids = {m["id"] for m in data.get("data", [])}
    ok = True
    for env, default in [("M3_MODEL", "openai/gpt-oss-20b"), ("M4_MODEL", "openai/gpt-oss-120b"), ("PROMPT_GUARD_MODEL", "meta-llama/llama-prompt-guard-2-86m")]:
        model = os.getenv(env, default)
        if model not in ids:
            ok &= report(f"groq: {model}", 404, "not in /models")
            continue
        status, data = call(f"{GROQ}/chat/completions", h, {"model": model, "messages": [{"role": "user", "content": "Reply with OK"}], "max_tokens": 32})
        ok &= report(f"groq: {model}", status, data)
    for stt in ("whisper-large-v3", "whisper-large-v3-turbo"):
        print(f"{'OK  ' if stt in ids else 'INFO'} groq: {stt:<39} {'listed' if stt in ids else 'not listed'} (fallback only)")
    return ok


def check_gemini(key):
    h = {"x-goog-api-key": key}
    status, data = call(f"{GEMINI}/models?pageSize=200", h)
    if not report("gemini: list models", status, data):
        return False
    listed = {m["name"].removeprefix("models/") for m in data.get("models", [])}
    m5 = os.getenv("M5_MODEL", "gemini-4-hydrogen")
    working = []
    for model in [m5, *[m for m in GEMINI_FALLBACKS if m != m5]]:
        if model not in listed:
            print(f"INFO gemini: {model:<38} not listed for this key")
            continue
        status, data = call(f"{GEMINI}/openai/chat/completions", {"Authorization": f"Bearer {key}"},
                            {"model": model, "messages": [{"role": "user", "content": "Reply with OK"}], "max_tokens": 32})
        if report(f"gemini (openai-compat): {model}", status, data):
            working.append(model)
    print(f"\nM5_MODEL={m5} -> {'WORKS' if m5 in working else 'FAILS'}; working Gemini models: {working or 'none'}")
    return m5 in working


def main():
    print(f"keys present: groq={bool(os.getenv('GROQ_API_KEY'))} gemini={bool(os.getenv('GEMINI_API_KEY'))}\n")
    ok = True
    ok &= check_groq(os.environ["GROQ_API_KEY"]) if os.getenv("GROQ_API_KEY") else report("groq key", 0, "missing")
    print()
    ok &= check_gemini(os.environ["GEMINI_API_KEY"]) if os.getenv("GEMINI_API_KEY") else report("gemini key", 0, "missing")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
