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
GATE = 90  # SPEC REVIEW gates on confidence, not on the score (D-020, raised in D-057)


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


def slices(closed=()):
    """Slice rows for the page plus {task: (slice, description)} from slices.md.

    A task counts as done when its checkbox is ticked or the log has a successful CLOSE for it,
    so the page does not lag while the loop has not ticked the checkbox yet.
    """
    rows, where, cur = [], {}, None
    for line in SLICES.read_text().splitlines() if SLICES.exists() else []:
        if m := re.match(r"## (S\d+): (.*)", line):
            cur = {"id": m[1], "name": m[2].split("(")[0].strip(), "done": 0, "total": 0}
            rows.append(cur)
        elif cur and (m := re.match(r"- \[([ x])\] \*\*(T-\d+)\*\*(.*)", line)):
            cur["total"] += 1
            cur["done"] += m[1] == "x" or m[2] in closed
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
    evs = [ev for ev in events() if not str(ev.get("task", "")).startswith("TMP-")]  # loop smoke test, not the project
    closed = {ev.get("task") for ev in evs if ev.get("step") in ("CLOSE", "COMMIT") and status(ev) == "ok"}
    rows, where = slices(closed)
    steps = [ev for ev in evs if ev.get("step") in STEPS]

    # Tasks run in parallel: keep the latest step of every task not closed yet, most recent last.
    running = {}
    for ev in steps:
        task = ev.get("task", "")
        if re.fullmatch(r"T-\d+", task) and task not in closed:
            running.pop(task, None)
            running[task] = ev

    cur = None
    last = steps[-1] if steps else None
    if last and last.get("task") in closed:
        last = next(reversed(running.values()), None)
    if last:
        task = last.get("task", "")
        mine = [ev for ev in steps if ev.get("task") == task]
        since = last.get("ts")
        for ev in reversed(mine):  # start of the current run of this step
            if ev["step"] != last["step"]:
                break
            since = ev.get("ts")
        slice_id, desc = where.get(task, (task if re.fullmatch(r"S\d+", task) else None, ""))
        seen = {ev["step"] for ev in steps if ev.get("task") in (task, slice_id)}  # SYNC is logged per slice
        size = next((ev["size"] for ev in reversed(mine) if ev.get("size")), None)
        cur = {"task": task, "title": f"{task} {desc}".strip()[:90], "slice": slice_id, "phase": phase(last),
               "status": "fail" if status(last) == "fail" else "start", "agent": last.get("agent", ""),
               "since": since, "detail": last.get("msg", ""), "size": f"classe {size}" if size else None,
               "skipped": [s.replace("_", " ") for s in STEPS[:STEPS.index(last["step"])] if s not in seen],
               "parallel": [f"{t} {phase(ev)}" for t, ev in running.items() if t != task]}
    active = {where[t][0] for t in running if t in where} | ({cur["slice"]} if cur and cur["slice"] else set())

    agents = {n: {"name": n, "model": m, "status": "idle"} for n, m in AGENTS.items()}
    latest, jobs = {}, {}  # jobs: agent -> {task: start event} still open (one agent type, many instances)
    reviews, votes, tries, commits = [], {}, {}, []
    for ev in evs:
        name, task = ev.get("agent", ""), ev.get("task", "")
        if name:
            latest[name] = ev
            mine = jobs.setdefault(name, {})
            if ev.get("status") == "start":
                mine[task] = ev
            elif ev.get("status") in END:
                mine.pop(task, None)
        if ev.get("step") in ("CLOSE", "COMMIT") and status(ev) == "ok":
            for mine in jobs.values():
                mine.pop(task, None)
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
    for name, ev in latest.items():
        run = list(jobs[name].values())
        agents[name] = {"name": name, "model": ev.get("model") or AGENTS.get(name, ""),
                        "status": "working" if run else "idle",
                        "detail": "  |  ".join(f"{e.get('task', '')} {phase(e)} · {e.get('msg', '')}" for e in run or [ev]),
                        "since": run[0].get("ts") if run else ev.get("ts")}

    feed = []
    for ev in evs[-500:]:
        raw, msg = ev.get("status", ""), ev.get("msg", "")
        if raw not in ("start", "ok", "fail", "done", ""):
            msg = f"{raw} · {msg}"
        feed.append({"ts": ev.get("ts"), "task": ev.get("task", ""), "phase": phase(ev),
                     "agent": ev.get("agent", ""), "status": status(ev), "msg": msg})

    return {"project": "TalentVisor", "loop": "agent loop", "gate": GATE,
            "phases": [s.replace("_", " ") for s in STEPS], "current": cur, "active": sorted(active),
            "agents": list(agents.values()), "slices": rows, "reviews": reviews, "commits": commits,
            "events": feed}


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
