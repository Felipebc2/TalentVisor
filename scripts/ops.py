"""Live ops for the agent loop: append events and serve the dashboard (scripts/ops.html). Stdlib only.

    python3 scripts/ops.py log task=T-03 step=BUILD agent=tv-builder model=sonnet status=start msg="db.py" size=M
    python3 scripts/ops.py log task=S0 step=SPEC_REVIEW agent=fork-neutra model=opus status=done score=4.2 conf=85
    make ops   # serves http://localhost:8001 from Docker; the page polls /state.json every 1 s

Dev tooling for docs/process/agent-loop.md (D-021); not part of the app.
"""

import json
import os
import re
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = Path(os.getenv("OPS_LOG", ROOT / "ops" / "events.jsonl"))
SLICES = ROOT / "docs" / "plan" / "slices.md"
PAGE = Path(__file__).with_name("ops.html")
STEPS = ["SYNC", "PICK", "SPEC", "SIZE", "BUILD", "VERIFY", "REVIEW", "FIX", "CLOSE", "SPEC_REVIEW", "COMMIT"]
AGENTS = {"tv-architect": "opus", "tv-builder": "sonnet", "tv-runner": "haiku", "tv-spec-reviewer": "opus",
          "fork-otimista": "opus", "fork-neutra": "opus", "fork-pessimista": "opus"}
END = {"ok", "fail", "changes", "approve", "pass", "revise", "human", "done"}
FAIL = {"fail", "changes", "revise", "human"}
GATE = 75  # SPEC REVIEW gates on confidence, not on the score (D-020)


def log(args):
    event = {"ts": datetime.now().astimezone().isoformat(timespec="seconds")}
    event.update(a.split("=", 1) for a in args if "=" in a)
    LOG.parent.mkdir(exist_ok=True)
    with LOG.open("a") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def events():
    try:
        lines = LOG.read_text().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue  # tolerate a half-written last line
    return out


def slices():
    """Slice rows for the page plus {task: (slice, description)} from the checkboxes in slices.md."""
    rows, where, cur = [], {}, None
    for line in SLICES.read_text().splitlines() if SLICES.exists() else []:
        if m := re.match(r"## (S\d+): (.*)", line):
            cur = {"id": m[1], "name": m[2].split("(")[0].strip(), "done": 0, "total": 0}
            rows.append(cur)
        elif cur and (m := re.match(r"- \[([ x])\] \*\*(T-\d+)\*\*(.*)", line)):
            cur["total"] += 1
            cur["done"] += m[1] == "x"
            where[m[2]] = (cur["id"], re.sub(r"`?\[[A-Z]+\]`?|[`*]", "", m[3].split(" *P")[0]).strip())
    return rows, where


def status(ev):
    raw = ev.get("status")
    return "start" if raw == "start" else "fail" if raw in FAIL else "ok"


def phase(ev):
    return str(ev.get("step", "")).replace("_", " ")


def nums(ev):
    """(score, conf) from the fields, or from a msg like 'nota 4.3 conf 85%'."""
    m = re.search(r"nota (\d+(?:\.\d+)?)\D+?(\d+(?:\.\d+)?)%", ev.get("msg", ""))
    score, conf = ev.get("score") or (m and m[1]), ev.get("conf") or (m and m[2])
    return (float(score) if score else None, float(conf) if conf else None)


def state():
    evs = events()
    rows, where = slices()
    steps = [ev for ev in evs if ev.get("step") in STEPS]

    cur = None
    if steps and not (steps[-1]["step"] == "COMMIT" and status(steps[-1]) == "ok"):
        last = steps[-1]
        task = last.get("task", "")
        mine = [ev for ev in steps if ev.get("task") == task]
        since = last.get("ts")
        for ev in reversed(mine):  # start of the current run of this step
            if ev["step"] != last["step"]:
                break
            since = ev.get("ts")
        seen = {ev["step"] for ev in mine}
        slice_id, desc = where.get(task, (task if re.fullmatch(r"S\d+", task) else None, ""))
        size = next((ev["size"] for ev in reversed(mine) if ev.get("size")), None)
        cur = {"task": task, "title": f"{task} {desc}".strip()[:90], "slice": slice_id, "phase": phase(last),
               "status": "fail" if status(last) == "fail" else "start", "agent": last.get("agent", ""),
               "since": since, "detail": last.get("msg", ""), "size": f"classe {size}" if size else None,
               "skipped": [s.replace("_", " ") for s in STEPS[:STEPS.index(last["step"])] if s not in seen]}

    agents = {n: {"name": n, "model": m, "status": "idle"} for n, m in AGENTS.items()}
    reviews, votes, tries, commits = [], {}, {}, []
    for ev in evs:
        name, task = ev.get("agent", ""), ev.get("task", "")
        if name:
            agents[name] = {"name": name, "model": ev.get("model") or AGENTS.get(name, ""),
                            "status": "idle" if ev.get("status") in END else "working",
                            "detail": f"{task} {phase(ev)} · {ev.get('msg', '')}", "since": ev.get("ts")}
        if ev.get("step") == "SPEC_REVIEW":
            score, conf = nums(ev)
            if name.startswith("fork-") and conf is not None:
                votes.setdefault(task, {})[name[5:]] = conf
            elif name == "tv-spec-reviewer" and score is not None:
                tries[task] = tries.get(task, 0) + 1
                gate = str(ev.get("gate", "")).upper()
                reviews.append({"slice": task, "attempt": tries[task], "score": score, "conf": conf,
                                "pass": gate == "PASS", "reason": f"{gate} · {ev.get('msg', '')}".strip(" ·"),
                                "ts": ev.get("ts"), "votes": votes.pop(task, None)})
        elif ev.get("step") == "COMMIT" and status(ev) == "ok":
            sha, _, subject = ev.get("msg", "").partition(" ")
            if not re.fullmatch(r"[0-9a-f]{7,40}", sha):
                sha, subject = "—", ev.get("msg", "")
            commits.append({"hash": sha, "msg": subject, "slice": task, "ts": ev.get("ts")})

    feed = []
    for ev in evs[-500:]:
        raw, msg = ev.get("status", ""), ev.get("msg", "")
        if raw not in ("start", "ok", "fail", "done", ""):
            msg = f"{raw} · {msg}"
        feed.append({"ts": ev.get("ts"), "task": ev.get("task", ""), "phase": phase(ev),
                     "agent": ev.get("agent", ""), "status": status(ev), "msg": msg})

    return {"project": "TalentVisor", "loop": "agent loop", "gate": GATE,
            "phases": [s.replace("_", " ") for s in STEPS], "current": cur, "agents": list(agents.values()),
            "slices": rows, "reviews": reviews, "commits": commits, "events": feed}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/state.json":
            body, ctype = json.dumps(state(), ensure_ascii=False).encode(), "application/json"
        elif self.path == "/":
            body, ctype = PAGE.read_bytes(), "text/html; charset=utf-8"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    if sys.argv[1:2] == ["log"]:
        log(sys.argv[2:])
    elif sys.argv[1:2] == ["serve"]:
        port = int(os.getenv("OPS_PORT", "8001"))
        print(f"live ops on http://localhost:{port}", flush=True)
        ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
    else:
        sys.exit(__doc__)
