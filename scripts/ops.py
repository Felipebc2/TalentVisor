"""Live ops for the agent loop: append events and serve a 1 s auto-refresh dashboard. Stdlib only.

    python3 scripts/ops.py log task=T-03 step=BUILD agent=tv-builder model=sonnet status=start msg="db.py"
    make ops   # serves http://localhost:8001 from Docker

Dev tooling for docs/process/agent-loop.md (D-021); not part of the app.
"""

import json
import os
import re
import sys
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = Path(os.getenv("OPS_LOG", ROOT / "ops" / "events.jsonl"))
SLICES = ROOT / "docs" / "plan" / "slices.md"
STEPS = ["SYNC", "PICK", "SPEC", "SIZE", "BUILD", "VERIFY", "REVIEW", "FIX", "CLOSE", "SPEC_REVIEW", "COMMIT"]
AGENTS = {"tv-architect": "opus", "tv-builder": "sonnet", "tv-runner": "haiku", "tv-spec-reviewer": "opus",
          "fork-otimista": "opus", "fork-neutra": "opus", "fork-pessimista": "opus"}
END = {"ok", "fail", "changes", "approve", "pass", "revise", "human", "done"}


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
    rows, cur = [], None
    for line in SLICES.read_text().splitlines() if SLICES.exists() else []:
        if m := re.match(r"## (S\d+): (.*)", line):
            cur = {"id": m[1], "name": m[2].split("(")[0].strip(), "done": 0, "total": 0}
            rows.append(cur)
        elif cur and (m := re.match(r"- \[([ x])\] \*\*T-", line)):
            cur["total"] += 1
            cur["done"] += m[1] == "x"
    return rows


def ago(ts):
    try:
        s = int((datetime.now().astimezone() - datetime.fromisoformat(ts)).total_seconds())
    except (TypeError, ValueError):
        return ""
    return f"{s}s" if s < 90 else f"{s // 60}m{s % 60:02d}s" if s < 3600 else f"{s // 3600}h{s % 3600 // 60:02d}m"


def e(x):
    return escape(str(x if x is not None else ""))


def fragment():
    evs = events()
    steps = [ev for ev in evs if ev.get("step") in STEPS]
    cur = steps[-1] if steps else {}
    agents = {name: None for name in AGENTS}
    for ev in evs:
        if ev.get("agent"):
            agents[ev["agent"]] = ev
    reviews = [ev for ev in evs if ev.get("step") == "SPEC_REVIEW" and ev.get("score")]
    commits = [ev for ev in evs if ev.get("step") == "COMMIT" and ev.get("status") in ("ok", None)]

    loop = "".join(
        f'<li class="{"on " + e(cur.get("status")) if s == cur.get("step") else ""}">{s.replace("_", " ")}</li>' for s in STEPS)
    head = (f'<section class="card now"><h2>Agora</h2><div class="big">{e(cur.get("task", "—"))} · {e(cur.get("step", "ocioso"))}</div>'
            f'<div>{e(cur.get("agent", ""))} <span class="st {e(cur.get("status"))}">{e(cur.get("status", ""))}</span> há {ago(cur.get("ts"))}</div>'
            f'<div class="msg">{e(cur.get("msg", ""))}</div><ol class="loop">{loop}</ol></section>')

    arows = ""
    for name, ev in agents.items():
        busy = ev is not None and ev.get("status") not in END
        state = "trabalhando" if busy else "ocioso"
        last = f'{e(ev.get("task"))} {e(ev.get("step"))} · {e(ev.get("msg"))}' if ev else "—"
        arows += (f'<tr class="{"busy" if busy else ""}"><td><span class="dot"></span>{e(name)}</td><td><span class="model {AGENTS[name]}">{AGENTS[name]}</span></td>'
                  f'<td>{state}</td><td class="msg">{last}</td><td>{ago(ev.get("ts")) if ev else ""}</td></tr>')

    srows = ""
    for s in slices():
        pct = 100 * s["done"] // s["total"] if s["total"] else 0
        srows += f'<tr><td>{e(s["id"])}</td><td>{e(s["name"])}</td><td><div class="bar"><i style="width:{pct}%"></i></div></td><td>{s["done"]}/{s["total"]}</td></tr>'

    rrows = "".join(
        f'<tr><td>{e(r.get("task"))}</td><td>{e(r.get("score"))}/5</td><td>{e(r.get("conf"))}%</td>'
        f'<td><span class="st {e(str(r.get("gate", "")).lower())}">{e(r.get("gate"))}</span></td><td class="msg">{e(r.get("msg"))}</td></tr>'
        for r in reversed(reviews[-8:])) or '<tr><td colspan="5" class="dim">nenhuma revisão ainda</td></tr>'
    crows = "".join(f'<li><code>{e(c.get("msg", ""))[:72]}</code> <span class="dim">{e(c.get("task"))} · {ago(c.get("ts"))}</span></li>'
                    for c in reversed(commits[-6:])) or '<li class="dim">nenhum commit ainda</li>'
    feed = "".join(
        f'<tr><td class="dim">{e(ev.get("ts", ""))[11:19]}</td><td>{e(ev.get("task"))}</td><td>{e(ev.get("step"))}</td>'
        f'<td>{e(ev.get("agent"))}</td><td><span class="st {e(ev.get("status"))}">{e(ev.get("status"))}</span></td><td class="msg">{e(ev.get("msg"))}</td></tr>'
        for ev in reversed(evs[-40:])) or '<tr><td colspan="6" class="dim">sem eventos em ops/events.jsonl</td></tr>'

    return (f'{head}<section class="card"><h2>Agentes</h2><table>{arows}</table></section>'
            f'<section class="card"><h2>Slices</h2><table>{srows}</table></section>'
            f'<section class="card"><h2>SPEC review (gate ≥ 75%)</h2><table><tr><th>slice</th><th>nota</th><th>conf.</th><th>gate</th><th>motivo</th></tr>{rrows}</table>'
            f'<h2>Commits</h2><ul class="commits">{crows}</ul></section>'
            f'<section class="card wide"><h2>Eventos ({len(evs)})</h2><table class="feed">{feed}</table></section>')


PAGE = """<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TalentVisor Live Ops</title><style>
:root{--bg:#0e1116;--card:#161b22;--line:#2a313c;--fg:#d6dde6;--dim:#7d8896;--acc:#58a6ff;--ok:#3fb950;--warn:#d29922;--bad:#f85149}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:14px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace}
header{display:flex;justify-content:space-between;align-items:center;padding:12px 16px;border-bottom:1px solid var(--line)}
header b{color:var(--acc)}#live{color:var(--ok)}#live.off{color:var(--bad)}
main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,460px),1fr));gap:12px;padding:12px 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;min-width:0}.wide{grid-column:1/-1}
h2{margin:0 0 8px;font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--dim)}
table{width:100%;border-collapse:collapse}td,th{padding:3px 6px;text-align:left;border-top:1px solid var(--line);vertical-align:top}th{color:var(--dim);font-weight:400}
.msg{color:var(--dim);overflow-wrap:anywhere}.dim{color:var(--dim)}.big{font-size:22px;color:var(--acc);margin-bottom:4px}
.loop{display:flex;flex-wrap:wrap;gap:4px;list-style:none;padding:0;margin:10px 0 0}.loop li{padding:2px 7px;border:1px solid var(--line);border-radius:4px;color:var(--dim);font-size:12px}
.loop li.on{border-color:var(--acc);color:#fff;background:#1f6feb33}.loop li.on.fail,.loop li.on.changes{border-color:var(--bad)}
.st{padding:0 6px;border-radius:4px;font-size:12px;background:#ffffff14}.st.start{color:var(--acc)}.st.ok,.st.approve,.st.pass,.st.done{color:var(--ok)}
.st.fail,.st.human{color:var(--bad)}.st.changes,.st.revise{color:var(--warn)}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;background:var(--line);margin-right:6px}tr.busy .dot{background:var(--ok);box-shadow:0 0 6px var(--ok);animation:p 1s infinite}
@keyframes p{50%{opacity:.35}}.model{font-size:11px;padding:0 5px;border-radius:3px}.opus{background:#a371f733;color:#d2a8ff}.sonnet{background:#1f6feb33;color:#79c0ff}.haiku{background:#3fb95033;color:#7ee787}
.bar{height:8px;background:var(--line);border-radius:4px;overflow:hidden;min-width:80px}.bar i{display:block;height:100%;background:var(--ok)}
.commits{margin:0;padding-left:18px}code{color:var(--fg)}
@media(prefers-reduced-motion:reduce){tr.busy .dot{animation:none}}
</style></head><body><header><div><b>TalentVisor</b> · Live Ops · agent loop</div><div><span id="live">● ao vivo</span> <span id="clock" class="dim"></span></div></header>
<main id="m">__FRAG__</main><script>
const m=document.getElementById('m'),live=document.getElementById('live'),clock=document.getElementById('clock');
setInterval(async()=>{try{const r=await fetch('/frag',{cache:'no-store'});m.innerHTML=await r.text();live.className='';live.textContent='● ao vivo'}
catch{live.className='off';live.textContent='● sem conexão'}clock.textContent=new Date().toLocaleTimeString('pt-BR')},1000);
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path not in ("/", "/frag"):
            self.send_error(404)
            return
        body = (fragment() if self.path == "/frag" else PAGE.replace("__FRAG__", fragment())).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
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
